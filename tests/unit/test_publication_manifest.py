from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "config/publication-manifest.schema.json").read_text())
EXAMPLE = json.loads((ROOT / "config/publication-manifest.example.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def _messages(instance: dict[str, Any]) -> list[str]:
    return [error.message for error in VALIDATOR.iter_errors(instance)]


def _set(path: tuple[str, ...], value: object) -> Callable[[dict[str, Any]], None]:
    def mutate(instance: dict[str, Any]) -> None:
        target: dict[str, Any] = instance
        for segment in path[:-1]:
            target = target[segment]
        target[path[-1]] = value

    return mutate


def test_publication_manifest_example_satisfies_strict_schema() -> None:
    Draft202012Validator.check_schema(SCHEMA)
    assert _messages(EXAMPLE) == []


@pytest.mark.parametrize(
    "mutate",
    [
        _set(("synthetic_only",), False),
        _set(("publication_id",), "unsafe-id"),
        _set(("code_commit",), "main"),
        _set(("dbt_candidate_build_fingerprint",), "not-a-fingerprint"),
        _set(("dbt_artifact_sha256",), "not-a-hash"),
        _set(("created_at_utc",), "2026-08-22T10:00:00-05:00"),
        _set(("membership_mode",), "replace"),
        _set(("full_bi_refresh_required",), True),
        _set(("gate_results",), []),
        _set(("row_reconciliations",), []),
        _set(("relation_inventories",), []),
        lambda instance: instance.update({"unexpected": "prohibited"}),
    ],
)
def test_publication_manifest_schema_rejects_unsafe_or_incomplete_evidence(
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    candidate = copy.deepcopy(EXAMPLE)
    mutate(candidate)

    assert _messages(candidate)
