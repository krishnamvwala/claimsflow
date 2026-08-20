"""Load the governed YAML source contracts into typed ingestion definitions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml  # type: ignore[import-untyped]


class ContractLoadError(ValueError):
    """Raised when the configured source-contract catalog is unsafe or incomplete."""


@dataclass(frozen=True, slots=True)
class FieldContract:
    """One source column and its machine-readable constraints."""

    name: str
    field_type: str
    nullable: bool
    allowed_values: tuple[str, ...]
    pattern: str | None
    minimum: str | int | float | None
    maximum: str | int | float | None
    minimum_exclusive: str | int | float | None


@dataclass(frozen=True, slots=True)
class SourceFileContract:
    """The contract view required to ingest one manifest file."""

    source_family: str
    dataset: str | None
    contract_id: str
    contract_version: str
    fields: tuple[FieldContract, ...]
    natural_key: tuple[str, ...]
    source_record_id: tuple[str, ...]
    required_rule_id: str
    required_rule_fields: tuple[str, ...]
    duplicate_rule_id: str

    @property
    def columns(self) -> tuple[str, ...]:
        return tuple(field.name for field in self.fields)

    @property
    def source_identity(self) -> str:
        suffix = f".{self.dataset}" if self.dataset is not None else ""
        return f"{self.source_family}{suffix}"

    @property
    def version_field(self) -> str:
        names = set(self.columns)
        if "source_updated_at" in names:
            return "source_updated_at"
        if "valid_from" in names:
            return "valid_from"
        raise ContractLoadError(f"{self.source_identity} has no version discriminator")


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractLoadError(f"{label} must be an object")
    return cast(dict[str, Any], value)


def _sequence(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ContractLoadError(f"{label} must be an array")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractLoadError(f"{label} must be a non-empty string")
    return value


def _key_fields(value: object, label: str) -> tuple[str, ...]:
    fields = tuple(_string(item, label) for item in _sequence(value, label))
    if not fields:
        raise ContractLoadError(f"{label} must not be empty")
    return fields


def _field(raw: object, label: str) -> FieldContract:
    value = _mapping(raw, label)
    if value.get("required") is not True:
        raise ContractLoadError(f"{label}.required must be true")
    if value.get("nullable") not in {True, False}:
        raise ContractLoadError(f"{label}.nullable must be a boolean")
    allowed = _sequence(value.get("allowed_values", []), f"{label}.allowed_values")
    pattern_value = value.get("pattern")
    if pattern_value is not None and not isinstance(pattern_value, str):
        raise ContractLoadError(f"{label}.pattern must be a string")
    boundaries: dict[str, str | int | float | None] = {}
    for name in ("minimum", "maximum", "minimum_exclusive"):
        boundary = value.get(name)
        if boundary is not None and (
            isinstance(boundary, bool) or not isinstance(boundary, (str, int, float))
        ):
            raise ContractLoadError(f"{label}.{name} must be a scalar number")
        boundaries[name] = boundary
    return FieldContract(
        name=_string(value.get("name"), f"{label}.name"),
        field_type=_string(value.get("type"), f"{label}.type"),
        nullable=value.get("nullable") is True,
        allowed_values=tuple(_string(item, f"{label}.allowed_values") for item in allowed),
        pattern=pattern_value,
        minimum=boundaries["minimum"],
        maximum=boundaries["maximum"],
        minimum_exclusive=boundaries["minimum_exclusive"],
    )


def _rule_ids(contract: dict[str, Any], source_family: str) -> tuple[str, str, str]:
    rules = [
        _mapping(item, f"{source_family}.validation_rules")
        for item in _sequence(contract.get("validation_rules"), f"{source_family}.validation_rules")
    ]
    required_rule = next(
        (rule for rule in rules if "empty" in str(rule.get("condition", ""))),
        None,
    )
    duplicate = next(
        (
            _string(rule.get("id"), "validation rule id")
            for rule in rules
            if "duplicate" in str(rule.get("condition", ""))
        ),
        None,
    )
    if required_rule is None or duplicate is None:
        raise ContractLoadError(
            f"{source_family} must declare required-field and duplicate-key validation rules"
        )
    return (
        _string(required_rule.get("id"), "validation rule id"),
        duplicate,
        _string(required_rule.get("condition"), "required-field rule condition"),
    )


def _required_rule_fields(
    fields: tuple[FieldContract, ...],
    natural_key: tuple[str, ...],
    condition: str,
) -> tuple[str, ...]:
    tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", condition))
    matched = tuple(field.name for field in fields if field.name in tokens)
    if matched:
        return matched
    return tuple(field for field in natural_key if field != "source_system")


class ContractCatalog:
    """Exact contract lookup for all eight families and fourteen generated files."""

    def __init__(self, contracts: dict[tuple[str, str | None], SourceFileContract]) -> None:
        self._contracts = contracts

    @classmethod
    def load(cls, directory: Path) -> ContractCatalog:
        """Load every governed YAML contract from an explicit directory."""

        root = directory.expanduser().absolute()
        if not root.is_dir() or root.is_symlink():
            raise ContractLoadError(f"contract directory is missing or unsafe: {root}")

        definitions: dict[tuple[str, str | None], SourceFileContract] = {}
        paths = sorted(root.glob("*.yml"))
        if len(paths) != 8:
            raise ContractLoadError(f"expected exactly 8 source contracts, found {len(paths)}")
        for path in paths:
            if path.is_symlink() or not path.is_file():
                raise ContractLoadError(f"source contract is missing or unsafe: {path}")
            try:
                contract = _mapping(yaml.safe_load(path.read_text(encoding="utf-8")), str(path))
            except (OSError, yaml.YAMLError) as error:
                raise ContractLoadError(
                    f"cannot load source contract {path.name}: {error}"
                ) from error
            source_family = _string(contract.get("source_family"), f"{path.name}.source_family")
            contract_id = _string(contract.get("contract_id"), f"{path.name}.contract_id")
            contract_version = str(contract.get("contract_version", ""))
            if contract.get("synthetic_only") is not True:
                raise ContractLoadError(f"{path.name} must remain synthetic_only")
            required_rule, duplicate_rule, required_condition = _rule_ids(contract, source_family)

            if source_family == "reference-data":
                for raw_dataset in _sequence(contract.get("datasets"), f"{path.name}.datasets"):
                    dataset = _mapping(raw_dataset, f"{path.name}.dataset")
                    dataset_name = _string(dataset.get("name"), f"{path.name}.dataset.name")
                    fields = tuple(
                        _field(item, f"{path.name}.{dataset_name}.schema")
                        for item in _sequence(dataset.get("schema"), "dataset.schema")
                    )
                    natural_key = _key_fields(
                        dataset.get("natural_key"), f"{path.name}.{dataset_name}.natural_key"
                    )
                    definition = SourceFileContract(
                        source_family=source_family,
                        dataset=dataset_name,
                        contract_id=contract_id,
                        contract_version=contract_version,
                        fields=fields,
                        natural_key=natural_key,
                        source_record_id=_key_fields(
                            dataset.get("source_record_id"),
                            f"{path.name}.{dataset_name}.source_record_id",
                        ),
                        required_rule_id=required_rule,
                        required_rule_fields=_required_rule_fields(
                            fields, natural_key, required_condition
                        ),
                        duplicate_rule_id=duplicate_rule,
                    )
                    definitions[(source_family, dataset_name)] = definition
                continue

            keys = _mapping(contract.get("keys"), f"{path.name}.keys")
            fields = tuple(
                _field(item, f"{path.name}.schema")
                for item in _sequence(contract.get("schema"), f"{path.name}.schema")
            )
            natural_key = _key_fields(keys.get("natural_key"), f"{path.name}.natural_key")
            definition = SourceFileContract(
                source_family=source_family,
                dataset=None,
                contract_id=contract_id,
                contract_version=contract_version,
                fields=fields,
                natural_key=natural_key,
                source_record_id=_key_fields(
                    keys.get("source_record_id"), f"{path.name}.source_record_id"
                ),
                required_rule_id=required_rule,
                required_rule_fields=_required_rule_fields(fields, natural_key, required_condition),
                duplicate_rule_id=duplicate_rule,
            )
            definitions[(source_family, None)] = definition

        if len(definitions) != 14:
            raise ContractLoadError(f"expected exactly 14 file contracts, found {len(definitions)}")
        return cls(definitions)

    def for_manifest_entry(self, entry: dict[str, Any]) -> SourceFileContract:
        """Resolve and bind a manifest entry to its exact governed contract."""

        source_family = entry.get("source_family")
        dataset = entry.get("dataset")
        if not isinstance(source_family, str) or not (dataset is None or isinstance(dataset, str)):
            raise ContractLoadError("manifest entry has an invalid source identity")
        definition = self._contracts.get((source_family, dataset))
        if definition is None:
            raise ContractLoadError(f"no governed contract for {(source_family, dataset)}")
        if entry.get("contract_id") != definition.contract_id:
            raise ContractLoadError(f"{definition.source_identity} contract ID does not match")
        if entry.get("contract_version") != definition.contract_version:
            raise ContractLoadError(f"{definition.source_identity} contract version does not match")
        return definition

    def identities(self) -> tuple[str, ...]:
        return tuple(sorted(definition.source_identity for definition in self._contracts.values()))

    def for_identity(self, source_identity: str) -> SourceFileContract:
        """Resolve a canonical source identity for correction revalidation."""

        matches = [
            definition
            for definition in self._contracts.values()
            if definition.source_identity == source_identity
        ]
        if len(matches) != 1:
            raise ContractLoadError(f"no unique governed contract for {source_identity}")
        return matches[0]
