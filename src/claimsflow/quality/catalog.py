"""Load versioned Phase 3 cross-source and freshness policy from governed YAML."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

import yaml  # type: ignore[import-untyped]

from claimsflow.domain.ingestion import Disposition
from claimsflow.domain.quality import QualitySeverity

RelationshipMatch = Literal["exact_key", "effective_at"]


class QualityCatalogError(ValueError):
    """Raised when cross-source validation policy is incomplete or contradictory."""


@dataclass(frozen=True, slots=True)
class PolicyRule:
    """One versioned row or batch rule."""

    rule_id: str
    severity: QualitySeverity
    disposition: Disposition | Literal["block_batch"]
    reason: str


@dataclass(frozen=True, slots=True)
class RelationshipSpec:
    """One contract relationship resolved by the Phase 3 engine."""

    fields: tuple[str, ...]
    target_identity: str
    target_fields: tuple[str, ...]
    required: bool
    match: RelationshipMatch
    cardinality: str
    as_of_field: str | None
    as_of_conversion: str | None
    every_list_member: bool
    rule: PolicyRule


@dataclass(frozen=True, slots=True)
class FreshnessSpec:
    """Source event field and governed ISO-8601 maximum age."""

    event_field: str
    maximum_source_age: str


@dataclass(frozen=True, slots=True)
class QualitySourceContract:
    """Relationship and freshness view of one source identity."""

    source_identity: str
    source_family: str
    dataset: str | None
    contract_id: str
    contract_version: str
    contract_sha256: str
    natural_key: tuple[str, ...]
    source_record_id: tuple[str, ...]
    required_rule_id: str
    duplicate_rule_id: str
    rules: tuple[PolicyRule, ...]
    relationships: tuple[RelationshipSpec, ...]
    freshness: FreshnessSpec


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise QualityCatalogError(f"{label} must be an object")
    return cast(dict[str, Any], value)


def _sequence(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise QualityCatalogError(f"{label} must be an array")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise QualityCatalogError(f"{label} must be a non-empty string")
    return value


def _read_yaml(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise QualityCatalogError(f"quality catalog file is missing or unsafe: {path}")
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise QualityCatalogError(f"quality catalog file cannot be read: {path}") from error
    return _mapping(value, str(path))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _rule(raw: object, label: str) -> PolicyRule:
    value = _mapping(raw, label)
    severity = _string(value.get("severity"), f"{label}.severity")
    if severity not in {"warning", "error", "critical"}:
        raise QualityCatalogError(f"{label}.severity is unsupported")
    disposition = _string(value.get("disposition"), f"{label}.disposition")
    if disposition not in {
        "accepted",
        "accepted_with_warning",
        "quarantined",
        "rejected",
        "block_batch",
    }:
        raise QualityCatalogError(f"{label}.disposition is unsupported")
    return PolicyRule(
        rule_id=_string(value.get("id"), f"{label}.id"),
        severity=cast(QualitySeverity, severity),
        disposition=cast(Disposition | Literal["block_batch"], disposition),
        reason=_string(value.get("reason"), f"{label}.reason"),
    )


def _contract_rule(raw: dict[str, Any], rule_id: str, label: str) -> PolicyRule:
    rules = _contract_rules(raw, label)
    rule = next((item for item in rules if item.rule_id == rule_id), None)
    if rule is None:
        raise QualityCatalogError(f"{label} does not declare mapped relationship rule {rule_id}")
    return rule


def _contract_rules(raw: dict[str, Any], label: str) -> tuple[PolicyRule, ...]:
    rules: list[PolicyRule] = []
    for item in (
        _mapping(value, f"{label}.validation_rules")
        for value in _sequence(raw.get("validation_rules"), f"{label}.validation_rules")
    ):
        rule_id = _string(item.get("id"), f"{label}.validation_rules.id")
        severity = _string(item.get("severity"), f"{label}.{rule_id}.severity")
        disposition = _string(item.get("disposition"), f"{label}.{rule_id}.disposition")
        if severity not in {"warning", "error", "critical"} or disposition not in {
            "accepted",
            "accepted_with_warning",
            "quarantined",
            "rejected",
            "block_batch",
        }:
            raise QualityCatalogError(f"{label}.{rule_id} has unsupported severity or disposition")
        rules.append(
            PolicyRule(
                rule_id=rule_id,
                severity=cast(QualitySeverity, severity),
                disposition=cast(Disposition | Literal["block_batch"], disposition),
                reason=_string(item.get("condition"), f"{label}.{rule_id}.condition"),
            )
        )
    if len({rule.rule_id for rule in rules}) != len(rules):
        raise QualityCatalogError(f"{label} contains duplicate validation rule IDs")
    return tuple(rules)


def _required_and_duplicate_rules(rules: tuple[PolicyRule, ...], label: str) -> tuple[str, str]:
    required = next((rule.rule_id for rule in rules if "empty" in rule.reason), None)
    duplicate = next((rule.rule_id for rule in rules if "duplicate" in rule.reason), None)
    if required is None or duplicate is None:
        raise QualityCatalogError(f"{label} lacks required-field or duplicate-key rules")
    return required, duplicate


def _key_fields(value: object, label: str) -> tuple[str, ...]:
    fields = tuple(_string(item, label) for item in _sequence(value, label))
    if not fields:
        raise QualityCatalogError(f"{label} must not be empty")
    return fields


def _scoped_field(value: object, dataset: str | None, label: str) -> str | None:
    field = _string(value, label)
    if "." not in field:
        return field
    prefix, unqualified = field.split(".", 1)
    return unqualified if dataset == prefix else None


def _duration_is_supported(value: str) -> bool:
    return re.fullmatch(r"PT(?:[0-9]+H)?(?:[0-9]+M)?", value) is not None and value != "PT"


class QualityCatalog:
    """Complete typed catalog for one immutable Phase 3 rule version."""

    def __init__(
        self,
        *,
        rule_version: str,
        contracts: tuple[QualitySourceContract, ...],
        freshness_rule: PolicyRule,
        batch_rules: dict[str, PolicyRule],
        policy_sha256: str,
        evaluation_interval: str,
    ) -> None:
        self.rule_version = rule_version
        self._contracts = {contract.source_identity: contract for contract in contracts}
        self.freshness_rule = freshness_rule
        self.batch_rules = batch_rules
        self.policy_sha256 = policy_sha256
        self.evaluation_interval = evaluation_interval

    @classmethod
    def load(cls, contracts_directory: Path, policy_path: Path) -> QualityCatalog:
        """Load all governed source relationships and the versioned cross-source policy."""

        policy = _read_yaml(policy_path)
        if policy.get("schema_version") != "1.0.0" or policy.get("synthetic_only") is not True:
            raise QualityCatalogError("quality policy must be schema 1.0.0 and synthetic_only=true")
        rule_version = _string(policy.get("rule_version"), "quality policy rule_version")
        evaluation_interval = _string(
            policy.get("evaluation_interval"), "quality policy evaluation_interval"
        )
        if not _duration_is_supported(evaluation_interval):
            raise QualityCatalogError("quality policy evaluation_interval is unsupported")
        freshness_rule = _rule(policy.get("freshness_rule"), "freshness_rule")
        if freshness_rule.disposition != "accepted_with_warning":
            raise QualityCatalogError("freshness rule must be a non-blocking warning")
        batch_values = _mapping(policy.get("batch_rules"), "batch_rules")
        required_batch_rules = {"missing_source", "reconciliation", "critical_outcome"}
        if set(batch_values) != required_batch_rules:
            raise QualityCatalogError("quality policy must declare the exact batch rule inventory")
        batch_rules = {
            name: _rule(value, f"batch_rules.{name}") for name, value in batch_values.items()
        }
        if any(rule.disposition != "block_batch" for rule in batch_rules.values()):
            raise QualityCatalogError("every batch rule must use block_batch disposition")

        relationship_policy = _mapping(policy.get("relationship_rules"), "relationship_rules")
        raw_contracts: list[tuple[str, str, str | None, dict[str, Any], dict[str, Any], str]] = []
        for path in sorted(contracts_directory.glob("*.yml")):
            raw = _read_yaml(path)
            contract_sha256 = _sha256(path)
            if raw.get("synthetic_only") is not True:
                raise QualityCatalogError(f"{path} must remain synthetic_only=true")
            family = _string(raw.get("source_family"), f"{path}.source_family")
            datasets = raw.get("datasets")
            if datasets is None:
                raw_contracts.append((family, family, None, raw, raw, contract_sha256))
            else:
                for dataset_value in _sequence(datasets, f"{path}.datasets"):
                    dataset_definition = _mapping(dataset_value, f"{path}.datasets")
                    dataset_name = _string(
                        dataset_definition.get("name"),
                        f"{path}.datasets.name",
                    )
                    raw_contracts.append(
                        (
                            f"{family}.{dataset_name}",
                            family,
                            dataset_name,
                            raw,
                            dataset_definition,
                            contract_sha256,
                        )
                    )
        identities = {identity for identity, _, _, _, _, _ in raw_contracts}

        contracts: list[QualitySourceContract] = []
        for identity, family, dataset, raw, definition, contract_sha256 in raw_contracts:
            contract_rules = _contract_rules(raw, identity)
            required_rule_id, duplicate_rule_id = _required_and_duplicate_rules(
                contract_rules, identity
            )
            keys = _mapping(raw.get("keys"), f"{identity}.keys") if dataset is None else definition
            policy_targets = _mapping(
                relationship_policy.get(identity, {}),
                f"relationship_rules.{identity}",
            )
            relationships: list[RelationshipSpec] = []
            for raw_relationship in _sequence(
                raw.get("relationships", []), f"{identity}.relationships"
            ):
                relationship = _mapping(raw_relationship, f"{identity}.relationships")
                scoped_fields = tuple(
                    _scoped_field(value, dataset, f"{identity}.relationships.fields")
                    for value in _sequence(
                        relationship.get("fields"), f"{identity}.relationships.fields"
                    )
                )
                if any(field is None for field in scoped_fields):
                    continue
                target = _string(relationship.get("target"), f"{identity}.relationships.target")
                target_identity = next(
                    (
                        candidate
                        for candidate in sorted(identities, key=len, reverse=True)
                        if target.startswith(f"{candidate}.")
                    ),
                    None,
                )
                if target_identity is None:
                    raise QualityCatalogError(
                        f"{identity} relationship target is unknown: {target}"
                    )
                target_fields = tuple(target[len(target_identity) + 1 :].split("+"))
                rule_id = policy_targets.get(target_identity)
                if not isinstance(rule_id, str):
                    raise QualityCatalogError(
                        f"relationship policy is missing {identity} -> {target_identity}"
                    )
                match = _string(relationship.get("match"), f"{identity}.relationships.match")
                if match not in {"exact_key", "effective_at"}:
                    raise QualityCatalogError(f"{identity} relationship match is unsupported")
                as_of = relationship.get("as_of_field")
                scoped_as_of = (
                    None
                    if as_of is None
                    else _scoped_field(as_of, dataset, f"{identity}.relationships.as_of_field")
                )
                if as_of is not None and scoped_as_of is None:
                    continue
                relationships.append(
                    RelationshipSpec(
                        fields=cast(tuple[str, ...], scoped_fields),
                        target_identity=target_identity,
                        target_fields=target_fields,
                        required=relationship.get("required") is True,
                        match=cast(RelationshipMatch, match),
                        cardinality=_string(
                            relationship.get("cardinality"),
                            f"{identity}.relationships.cardinality",
                        ),
                        as_of_field=scoped_as_of,
                        as_of_conversion=cast(str | None, relationship.get("as_of_conversion")),
                        every_list_member=relationship.get("mode") == "every_list_member",
                        rule=_contract_rule(raw, rule_id, identity),
                    )
                )
            if set(policy_targets) != {item.target_identity for item in relationships}:
                raise QualityCatalogError(
                    f"relationship policy for {identity} contains unused targets"
                )
            freshness = _mapping(raw.get("freshness"), f"{identity}.freshness")
            maximum_age = _string(
                freshness.get("maximum_source_age"), f"{identity}.maximum_source_age"
            )
            if not _duration_is_supported(maximum_age):
                raise QualityCatalogError(f"{identity} maximum source age is unsupported")
            contracts.append(
                QualitySourceContract(
                    source_identity=identity,
                    source_family=family,
                    dataset=dataset,
                    contract_id=_string(raw.get("contract_id"), f"{identity}.contract_id"),
                    contract_version=_string(
                        str(raw.get("contract_version", "")), f"{identity}.contract_version"
                    ),
                    contract_sha256=contract_sha256,
                    natural_key=_key_fields(keys.get("natural_key"), f"{identity}.natural_key"),
                    source_record_id=_key_fields(
                        keys.get("source_record_id"), f"{identity}.source_record_id"
                    ),
                    required_rule_id=required_rule_id,
                    duplicate_rule_id=duplicate_rule_id,
                    rules=contract_rules,
                    relationships=tuple(relationships),
                    freshness=FreshnessSpec(
                        event_field=_string(
                            freshness.get("event_field"), f"{identity}.event_field"
                        ),
                        maximum_source_age=maximum_age,
                    ),
                )
            )
        unused_sources = set(relationship_policy) - identities
        if unused_sources:
            raise QualityCatalogError(
                f"quality policy has unknown sources: {sorted(unused_sources)}"
            )
        return cls(
            rule_version=rule_version,
            contracts=tuple(contracts),
            freshness_rule=freshness_rule,
            batch_rules=batch_rules,
            policy_sha256=_sha256(policy_path),
            evaluation_interval=evaluation_interval,
        )

    def identities(self) -> tuple[str, ...]:
        """Return the exact governed source identity inventory."""

        return tuple(sorted(self._contracts))

    def for_identity(self, source_identity: str) -> QualitySourceContract:
        """Return one contract or fail closed for an unknown source."""

        try:
            return self._contracts[source_identity]
        except KeyError as error:
            raise QualityCatalogError(
                f"unknown quality source identity: {source_identity}"
            ) from error

    def rule_for(self, source_identity: str, rule_id: str) -> PolicyRule:
        """Return a source rule by stable ID or fail closed."""

        contract = self.for_identity(source_identity)
        rule = next((item for item in contract.rules if item.rule_id == rule_id), None)
        if rule is None:
            raise QualityCatalogError(f"{source_identity} does not declare rule {rule_id}")
        return rule

    def contract_inventory(self) -> tuple[dict[str, str], ...]:
        """Return exact identity-level contract evidence for run binding."""

        return tuple(
            {
                "source_identity": contract.source_identity,
                "contract_id": contract.contract_id,
                "contract_version": contract.contract_version,
                "sha256": contract.contract_sha256,
            }
            for contract in sorted(self._contracts.values(), key=lambda item: item.source_identity)
        )

    def all_rule_ids(self) -> tuple[str, ...]:
        """Return every source-contract rule ID governed by this catalog."""

        return tuple(
            sorted(
                {rule.rule_id for contract in self._contracts.values() for rule in contract.rules}
            )
        )
