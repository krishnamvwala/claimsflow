"""ClaimsFlow developer command-line interface."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TextIO

from claimsflow.config import ConfigurationError, RuntimeSettings
from claimsflow.generator import GenerationConfig, GenerationError, generate_delivery
from claimsflow.ingestion import IngestionError, ingest_delivery


def build_parser() -> argparse.ArgumentParser:
    """Create the command parser without reading process state."""

    parser = argparse.ArgumentParser(prog="claimsflow")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "doctor", help="validate non-secret runtime configuration and print a safe summary"
    )
    generate = subparsers.add_parser(
        "generate",
        help="create one deterministic synthetic source delivery and provenance manifest",
    )
    generate.add_argument(
        "--output",
        required=True,
        type=Path,
        help="new output directory; existing paths are never overwritten",
    )
    generate.add_argument(
        "--service-month",
        required=True,
        help="fictional service period in YYYY-MM format",
    )
    generate.add_argument(
        "--claims",
        default=1_000,
        type=int,
        help="claim count from 1 through 100000 (default: 1000)",
    )
    generate.add_argument(
        "--seed",
        default=20_260_815,
        type=int,
        help="repeatability seed from 0 through 2147483647 (default: 20260815)",
    )
    ingest = subparsers.add_parser(
        "ingest",
        help="verify and locally register one synthetic delivery without cloud writes",
    )
    ingest.add_argument(
        "--manifest",
        required=True,
        type=Path,
        help="generator manifest.json to verify before any local landing write",
    )
    ingest.add_argument(
        "--workspace",
        required=True,
        type=Path,
        help="local control-plane and batch-artifact directory",
    )
    ingest.add_argument(
        "--contracts",
        default=Path("contracts/source-data"),
        type=Path,
        help="governed source-contract directory (default: contracts/source-data)",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run the CLI and return a process exit code."""

    output = sys.stdout if stdout is None else stdout
    error_output = sys.stderr if stderr is None else stderr
    arguments = build_parser().parse_args(list(argv) if argv is not None else None)

    if arguments.command == "doctor":
        try:
            settings = RuntimeSettings.from_mapping(os.environ if environ is None else environ)
        except ConfigurationError as error:
            print(json.dumps({"status": "error", "reason": str(error)}), file=error_output)
            return 2
        print(
            json.dumps({"status": "ok", **settings.public_summary()}, sort_keys=True),
            file=output,
        )
        return 0

    if arguments.command == "generate":
        try:
            RuntimeSettings.from_mapping(os.environ if environ is None else environ)
            config = GenerationConfig.from_values(
                seed=arguments.seed,
                claim_count=arguments.claims,
                service_month=arguments.service_month,
            )
            generation_result = generate_delivery(config, arguments.output)
        except (ConfigurationError, GenerationError, OSError) as error:
            print(json.dumps({"status": "error", "reason": str(error)}), file=error_output)
            return 2
        print(
            json.dumps(
                {
                    "status": "ok",
                    "synthetic_only": True,
                    "batch_id": generation_result.batch_id,
                    "output_directory": str(generation_result.output_directory),
                    "manifest": str(generation_result.manifest_path),
                    "file_count": generation_result.file_count,
                    "total_rows": generation_result.total_rows,
                },
                sort_keys=True,
            ),
            file=output,
        )
        return 0

    if arguments.command == "ingest":
        try:
            RuntimeSettings.from_mapping(os.environ if environ is None else environ)
            ingestion_result = ingest_delivery(
                arguments.manifest,
                arguments.workspace,
                arguments.contracts,
            )
        except (ConfigurationError, IngestionError, OSError) as error:
            print(json.dumps({"status": "error", "reason": str(error)}), file=error_output)
            return 2
        print(
            json.dumps(
                {
                    "status": "ok",
                    "synthetic_only": True,
                    "decision": ingestion_result.decision,
                    "batch_id": ingestion_result.batch_id,
                    "workspace": str(ingestion_result.workspace),
                    "artifact_directory": str(ingestion_result.artifact_directory),
                    "report": str(ingestion_result.report_path),
                    "file_count": ingestion_result.file_count,
                    "processed_files": ingestion_result.processed_files,
                    "duplicate_files": ingestion_result.duplicate_files,
                    "declared_rows": ingestion_result.declared_rows,
                    "raw_rows": ingestion_result.raw_rows,
                    "duplicate_no_op_rows": ingestion_result.duplicate_no_op_rows,
                    "accepted": ingestion_result.accepted,
                    "warned": ingestion_result.warned,
                    "quarantined": ingestion_result.quarantined,
                    "rejected": ingestion_result.rejected,
                    "reconciled": ingestion_result.reconciled,
                },
                sort_keys=True,
            ),
            file=output,
        )
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
