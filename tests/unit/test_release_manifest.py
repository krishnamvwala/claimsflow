from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "config/release-manifest.schema.json").read_text())
EXAMPLE = json.loads((ROOT / "config/release-manifest.example.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def validation_messages(instance: dict[str, Any]) -> list[str]:
    return [error.message for error in VALIDATOR.iter_errors(instance)]


def set_value(path: tuple[str, ...], value: object) -> Callable[[dict[str, Any]], None]:
    def mutate(instance: dict[str, Any]) -> None:
        target: dict[str, Any] = instance
        for segment in path[:-1]:
            target = target[segment]
        target[path[-1]] = value

    return mutate


def test_release_manifest_example_satisfies_complete_schema() -> None:
    Draft202012Validator.check_schema(SCHEMA)
    assert validation_messages(EXAMPLE) == []


@pytest.mark.parametrize(
    "mutate",
    [
        set_value(("synthetic_only",), "true"),
        set_value(("git_commit",), "not-a-forty-character-sha"),
        set_value(("approved_at_utc",), "2026-08-14T01:00:00-05:00"),
        set_value(("contract_version",), 1),
        set_value(("component_versions", "dbt_core"), None),
        set_value(("component_versions", "python"), ""),
        set_value(("component_versions", "airflow"), "latest"),
        set_value(("contract_version",), ""),
        set_value(("contract_version",), "x"),
        set_value(("dictionary_version",), ""),
        set_value(("dictionary_version",), "x"),
        lambda instance: instance.update({"unexpected": "prohibited"}),
    ],
    ids=[
        "invalid-type",
        "invalid-commit-hash",
        "non-utc-approval-date",
        "invalid-governed-version-type",
        "invalid-component-version-type",
        "blank-python-version",
        "malformed-component-version",
        "blank-contract-version",
        "malformed-contract-version",
        "blank-dictionary-version",
        "malformed-dictionary-version",
        "additional-property",
    ],
)
def test_release_manifest_schema_rejects_invalid_evidence(
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    candidate = copy.deepcopy(EXAMPLE)
    mutate(candidate)

    assert validation_messages(candidate)
