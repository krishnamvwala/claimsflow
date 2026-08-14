"""ClaimsFlow developer command-line interface."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from typing import TextIO

from claimsflow.config import ConfigurationError, RuntimeSettings


def build_parser() -> argparse.ArgumentParser:
    """Create the command parser without reading process state."""

    parser = argparse.ArgumentParser(prog="claimsflow")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "doctor", help="validate non-secret runtime configuration and print a safe summary"
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

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
