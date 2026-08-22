"""Transactional BigQuery repository for immutable publication-control evidence."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from importlib import import_module
from typing import Protocol, cast

from claimsflow.domain.publication import (
    ActivationEvent,
    ActivePublication,
    CandidateInventoryEntry,
    MembershipDeltaEntry,
    PublicationCandidate,
    PublicationEnvironment,
    PublicationManifest,
    ResultVersionReference,
)

_PROJECT_ID = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
_RELATION_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,1023}$")

type QueryParameterValues = Mapping[str, tuple[str, object]]
type QueryConfigFactory = Callable[[QueryParameterValues], object]


class BigQueryPublicationError(RuntimeError):
    """Raised when BigQuery cannot prove publication state or pointer safety."""


class _QueryJob(Protocol):
    def result(
        self,
        *,
        timeout: float | None = None,
    ) -> Iterable[Mapping[str, object]]: ...


class _BigQueryClient(Protocol):
    def query(
        self,
        query: str,
        *,
        location: str,
        job_config: object,
    ) -> _QueryJob: ...


def _query_config(parameters: QueryParameterValues) -> object:
    bigquery = import_module("google.cloud.bigquery")
    return cast(
        object,
        bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter(name, type_name, value)
                for name, (type_name, value) in parameters.items()
            ]
        ),
    )


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _candidate_fingerprint(candidate: PublicationCandidate) -> str:
    canonical = _canonical_json(
        {
            "manifest": candidate.manifest.as_dict(),
            "membership_delta": [item.as_dict() for item in candidate.membership_delta],
            "result_versions": [item.as_dict() for item in candidate.result_versions],
            "inventory": [item.as_dict() for item in candidate.inventory],
        }
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class GoogleBigQueryPublicationRepository:
    """Persists candidates create-only and moves the active pointer transactionally."""

    def __init__(
        self,
        client: _BigQueryClient,
        *,
        project: str,
        dataset: str = "claimsflow_audit",
        location: str = "US",
        query_config_factory: QueryConfigFactory = _query_config,
        query_timeout_seconds: float = 300.0,
        max_membership_chain_depth: int = 8,
    ) -> None:
        if _PROJECT_ID.fullmatch(project) is None:
            raise ValueError("project must be a valid lowercase Google Cloud project ID")
        if _RELATION_ID.fullmatch(dataset) is None:
            raise ValueError("dataset must be a safe BigQuery dataset ID")
        if not location.strip():
            raise ValueError("location cannot be blank")
        if query_timeout_seconds <= 0:
            raise ValueError("query_timeout_seconds must be positive")
        if max_membership_chain_depth <= 0:
            raise ValueError("max_membership_chain_depth must be positive")
        self._client = client
        self.project = project
        self.dataset = dataset
        self.location = location
        self._query_config_factory = query_config_factory
        self._query_timeout_seconds = query_timeout_seconds
        self._max_membership_chain_depth = max_membership_chain_depth

    @classmethod
    def from_default_credentials(
        cls,
        *,
        project: str,
        dataset: str = "claimsflow_audit",
        location: str = "US",
    ) -> GoogleBigQueryPublicationRepository:
        """Compose the repository with Application Default Credentials when requested."""

        bigquery = import_module("google.cloud.bigquery")
        client = cast(_BigQueryClient, bigquery.Client(project=project, location=location))
        return cls(client, project=project, dataset=dataset, location=location)

    def _table(self, name: str) -> str:
        if _RELATION_ID.fullmatch(name) is None:
            raise ValueError("publication table name is unsafe")
        return f"`{self.project}.{self.dataset}.{name}`"

    def _query(
        self,
        sql: str,
        parameters: QueryParameterValues | None = None,
    ) -> tuple[Mapping[str, object], ...]:
        job = self._client.query(
            sql,
            location=self.location,
            job_config=self._query_config_factory(parameters or {}),
        )
        try:
            return tuple(job.result(timeout=self._query_timeout_seconds))
        except Exception as error:
            raise BigQueryPublicationError("BigQuery publication operation failed") from error

    def ensure_schema(self) -> None:
        """Create governed control tables and preseed rows used for serialized mutations."""

        manifests = self._table("publication_manifests")
        deltas = self._table("publication_membership_deltas")
        versions = self._table("publication_result_versions")
        inventories = self._table("publication_candidate_inventory")
        active = self._table("active_publications")
        activations = self._table("publication_activations")
        locks = self._table("publication_reservation_locks")
        self._query(
            f"""-- claimsflow:ensure_publication_schema
CREATE TABLE IF NOT EXISTS {manifests} (
  publication_id STRING NOT NULL,
  environment STRING NOT NULL,
  parent_publication_id STRING,
  membership_delta_chain ARRAY<STRING> NOT NULL,
  membership_mode STRING NOT NULL,
  manifest_fingerprint STRING NOT NULL,
  candidate_fingerprint STRING NOT NULL,
  manifest_json JSON NOT NULL,
  created_at_utc TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at_utc)
CLUSTER BY environment, publication_id;

CREATE TABLE IF NOT EXISTS {deltas} (
  publication_id STRING NOT NULL,
  sequence INT64 NOT NULL,
  logical_relation STRING NOT NULL,
  business_key STRING NOT NULL,
  result_version_id STRING,
  tombstone BOOL NOT NULL
)
CLUSTER BY publication_id, logical_relation, business_key;

CREATE TABLE IF NOT EXISTS {versions} (
  result_version_id STRING NOT NULL,
  source_publication_id STRING NOT NULL,
  logical_relation STRING NOT NULL,
  business_key STRING NOT NULL,
  result_sha256 STRING NOT NULL,
  physical_relation STRING NOT NULL
)
CLUSTER BY result_version_id, logical_relation, business_key;

CREATE TABLE IF NOT EXISTS {inventories} (
  publication_id STRING NOT NULL,
  inventory_sequence INT64 NOT NULL,
  logical_relation STRING NOT NULL,
  business_key STRING NOT NULL,
  result_sha256 STRING NOT NULL
)
CLUSTER BY publication_id, logical_relation, business_key;

CREATE TABLE IF NOT EXISTS {active}
CLUSTER BY environment AS
SELECT
  environment,
  CAST(NULL AS STRING) AS publication_id,
  0 AS revision,
  TIMESTAMP '1970-01-01 00:00:00+00' AS updated_at_utc
FROM UNNEST(['local', 'dev-demo']) AS environment;

CREATE TABLE IF NOT EXISTS {activations} (
  event_id STRING NOT NULL,
  kind STRING NOT NULL,
  environment STRING NOT NULL,
  from_publication_id STRING,
  to_publication_id STRING NOT NULL,
  from_revision INT64 NOT NULL,
  to_revision INT64 NOT NULL,
  reason STRING NOT NULL,
  activated_at_utc TIMESTAMP NOT NULL
)
PARTITION BY DATE(activated_at_utc)
CLUSTER BY environment, to_publication_id, kind;

CREATE TABLE IF NOT EXISTS {locks}
CLUSTER BY lock_bucket AS
SELECT lock_bucket, 0 AS revision
FROM UNNEST(GENERATE_ARRAY(0, 63)) AS lock_bucket;

ASSERT (
  SELECT COUNT(*) = 2
    AND COUNT(DISTINCT environment) = 2
    AND COUNTIF(environment NOT IN ('local', 'dev-demo')) = 0
  FROM {active}
) AS 'active publication control rows are not exactly preseeded';

ASSERT (
  SELECT COUNT(*) = 64
    AND COUNT(DISTINCT lock_bucket) = 64
    AND COUNTIF(lock_bucket NOT BETWEEN 0 AND 63) = 0
  FROM {locks}
) AS 'publication reservation locks are not exactly preseeded';
"""
        )

    def get_manifest(self, publication_id: str) -> PublicationManifest | None:
        rows = self._query(
            f"""-- claimsflow:get_publication_manifest
SELECT manifest_json
FROM {self._table("publication_manifests")}
WHERE publication_id = @publication_id
""",
            {"publication_id": ("STRING", publication_id)},
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise BigQueryPublicationError("publication identity is not unique")
        raw = rows[0]["manifest_json"]
        value = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(value, dict):
            raise BigQueryPublicationError("persisted publication manifest is malformed")
        return PublicationManifest.from_dict(cast(dict[str, object], value))

    def get_membership_delta(
        self,
        publication_id: str,
    ) -> tuple[MembershipDeltaEntry, ...]:
        rows = self._query(
            f"""-- claimsflow:get_membership_delta
SELECT sequence, logical_relation, business_key, result_version_id, tombstone
FROM {self._table("publication_membership_deltas")}
WHERE publication_id = @publication_id
ORDER BY sequence
""",
            {"publication_id": ("STRING", publication_id)},
        )
        return tuple(
            MembershipDeltaEntry(
                sequence=int(cast(int, row["sequence"])),
                logical_relation=str(row["logical_relation"]),
                business_key=str(row["business_key"]),
                result_version_id=(
                    str(row["result_version_id"])
                    if row.get("result_version_id") is not None
                    else None
                ),
                tombstone=bool(row["tombstone"]),
            )
            for row in rows
        )

    def get_result_version(self, result_version_id: str) -> ResultVersionReference | None:
        rows = self._query(
            f"""-- claimsflow:get_result_version
SELECT
  result_version_id,
  source_publication_id,
  logical_relation,
  business_key,
  result_sha256,
  physical_relation
FROM {self._table("publication_result_versions")}
WHERE result_version_id = @result_version_id
""",
            {"result_version_id": ("STRING", result_version_id)},
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise BigQueryPublicationError("result-version identity is not unique")
        row = rows[0]
        return ResultVersionReference(
            result_version_id=str(row["result_version_id"]),
            source_publication_id=str(row["source_publication_id"]),
            logical_relation=str(row["logical_relation"]),
            business_key=str(row["business_key"]),
            result_sha256=str(row["result_sha256"]),
            physical_relation=str(row["physical_relation"]),
        )

    def get_candidate_inventory(
        self,
        publication_id: str,
    ) -> tuple[CandidateInventoryEntry, ...]:
        rows = self._query(
            f"""-- claimsflow:get_candidate_inventory
SELECT logical_relation, business_key, result_sha256
FROM {self._table("publication_candidate_inventory")}
WHERE publication_id = @publication_id
ORDER BY inventory_sequence
""",
            {"publication_id": ("STRING", publication_id)},
        )
        return tuple(
            CandidateInventoryEntry(
                logical_relation=str(row["logical_relation"]),
                business_key=str(row["business_key"]),
                result_sha256=str(row["result_sha256"]),
            )
            for row in rows
        )

    def append_candidate(self, candidate: PublicationCandidate) -> None:
        """Create a manifest, delta, and new result references in one transaction."""

        manifest = candidate.manifest
        manifests = self._table("publication_manifests")
        deltas = self._table("publication_membership_deltas")
        versions = self._table("publication_result_versions")
        inventories = self._table("publication_candidate_inventory")
        locks = self._table("publication_reservation_locks")
        reservation_bucket = (
            int.from_bytes(
                hashlib.sha256(manifest.publication_id.encode("utf-8")).digest()[:8],
                byteorder="big",
                signed=False,
            )
            % 64
        )
        self._query(
            f"""-- claimsflow:append_publication_candidate
BEGIN TRANSACTION;

UPDATE {locks}
SET revision = revision + 1
WHERE lock_bucket = @reservation_bucket;
ASSERT @@row_count = 1 AS 'publication reservation lock is unavailable';

ASSERT (
  SELECT COUNT(*) = 0
  FROM {manifests}
  WHERE publication_id = @publication_id
    AND candidate_fingerprint != @candidate_fingerprint
) AS 'publication_id is already bound to different immutable evidence';

ASSERT (
  SELECT COUNT(*) <= 1
  FROM {manifests}
  WHERE publication_id = @publication_id
) AS 'publication_id is not unique';

IF NOT EXISTS (
  SELECT 1 FROM {manifests} WHERE publication_id = @publication_id
) THEN
  INSERT INTO {manifests} (
    publication_id,
    environment,
    parent_publication_id,
    membership_delta_chain,
    membership_mode,
    manifest_fingerprint,
    candidate_fingerprint,
    manifest_json,
    created_at_utc
  )
  VALUES (
    @publication_id,
    @environment,
    @parent_publication_id,
    ARRAY(
      SELECT JSON_VALUE(item)
      FROM UNNEST(
        JSON_QUERY_ARRAY(PARSE_JSON(@manifest_json), '$.membership_delta_chain')
      ) AS item
    ),
    @membership_mode,
    @manifest_fingerprint,
    @candidate_fingerprint,
    PARSE_JSON(@manifest_json),
    @created_at_utc
  );

  INSERT INTO {deltas} (
    publication_id,
    sequence,
    logical_relation,
    business_key,
    result_version_id,
    tombstone
  )
  SELECT
    @publication_id,
    CAST(JSON_VALUE(item, '$.sequence') AS INT64),
    JSON_VALUE(item, '$.logical_relation'),
    JSON_VALUE(item, '$.business_key'),
    JSON_VALUE(item, '$.result_version_id'),
    CAST(JSON_VALUE(item, '$.tombstone') AS BOOL)
  FROM UNNEST(JSON_QUERY_ARRAY(PARSE_JSON(@membership_delta_json))) AS item;

  ASSERT (
    SELECT COUNT(*) = 0
    FROM UNNEST(JSON_QUERY_ARRAY(PARSE_JSON(@result_versions_json))) AS item
    JOIN {versions} AS existing
      ON existing.result_version_id = JSON_VALUE(item, '$.result_version_id')
    WHERE existing.source_publication_id != JSON_VALUE(item, '$.source_publication_id')
      OR existing.logical_relation != JSON_VALUE(item, '$.logical_relation')
      OR existing.business_key != JSON_VALUE(item, '$.business_key')
      OR existing.result_sha256 != JSON_VALUE(item, '$.result_sha256')
      OR existing.physical_relation != JSON_VALUE(item, '$.physical_relation')
  ) AS 'result_version_id is already bound to different immutable evidence';

  INSERT INTO {versions} (
    result_version_id,
    source_publication_id,
    logical_relation,
    business_key,
    result_sha256,
    physical_relation
  )
  SELECT
    JSON_VALUE(item, '$.result_version_id'),
    JSON_VALUE(item, '$.source_publication_id'),
    JSON_VALUE(item, '$.logical_relation'),
    JSON_VALUE(item, '$.business_key'),
    JSON_VALUE(item, '$.result_sha256'),
    JSON_VALUE(item, '$.physical_relation')
  FROM UNNEST(JSON_QUERY_ARRAY(PARSE_JSON(@result_versions_json))) AS item
  WHERE NOT EXISTS (
    SELECT 1
    FROM {versions} AS existing
    WHERE existing.result_version_id = JSON_VALUE(item, '$.result_version_id')
  );

  ASSERT (
    SELECT COUNT(*) = 0
    FROM {deltas} AS delta
    LEFT JOIN {versions} AS result_version
      ON result_version.result_version_id = delta.result_version_id
    WHERE delta.publication_id = @publication_id
      AND NOT delta.tombstone
      AND result_version.result_version_id IS NULL
  ) AS 'membership references an unavailable result version';

  INSERT INTO {inventories} (
    publication_id,
    inventory_sequence,
    logical_relation,
    business_key,
    result_sha256
  )
  SELECT
    @publication_id,
    inventory_sequence,
    JSON_VALUE(item, '$.logical_relation'),
    JSON_VALUE(item, '$.business_key'),
    JSON_VALUE(item, '$.result_sha256')
  FROM UNNEST(JSON_QUERY_ARRAY(PARSE_JSON(@inventory_json))) AS item
    WITH OFFSET AS inventory_sequence;
END IF;

COMMIT TRANSACTION;
""",
            {
                "publication_id": ("STRING", manifest.publication_id),
                "environment": ("STRING", manifest.environment),
                "parent_publication_id": ("STRING", manifest.parent_publication_id),
                "membership_mode": ("STRING", manifest.membership_mode),
                "manifest_fingerprint": ("STRING", manifest.fingerprint),
                "candidate_fingerprint": ("STRING", _candidate_fingerprint(candidate)),
                "manifest_json": ("STRING", _canonical_json(manifest.as_dict())),
                "membership_delta_json": (
                    "STRING",
                    _canonical_json([item.as_dict() for item in candidate.membership_delta]),
                ),
                "result_versions_json": (
                    "STRING",
                    _canonical_json([item.as_dict() for item in candidate.result_versions]),
                ),
                "inventory_json": (
                    "STRING",
                    _canonical_json([item.as_dict() for item in candidate.inventory]),
                ),
                "reservation_bucket": ("INT64", reservation_bucket),
                "created_at_utc": ("TIMESTAMP", manifest.created_at_utc),
            },
        )

    def get_active(
        self,
        environment: PublicationEnvironment,
    ) -> ActivePublication | None:
        rows = self._query(
            f"""-- claimsflow:get_active_publication
SELECT environment, publication_id, revision, updated_at_utc
FROM {self._table("active_publications")}
WHERE environment = @environment
""",
            {"environment": ("STRING", environment)},
        )
        if len(rows) != 1:
            raise BigQueryPublicationError(
                "active publication control row is missing or not unique"
            )
        row = rows[0]
        if row.get("publication_id") is None:
            if int(cast(int, row["revision"])) != 0:
                raise BigQueryPublicationError(
                    "uninitialized active publication has a nonzero revision"
                )
            return None
        updated = row["updated_at_utc"]
        if not isinstance(updated, datetime):
            raise BigQueryPublicationError("active publication timestamp is malformed")
        return ActivePublication(
            environment=cast(PublicationEnvironment, str(row["environment"])),
            publication_id=str(row["publication_id"]),
            revision=int(cast(int, row["revision"])),
            updated_at_utc=updated,
        )

    def compare_and_swap_active(
        self,
        event: ActivationEvent,
        *,
        expected_publication_id: str | None,
        expected_revision: int,
    ) -> ActivePublication:
        if (
            event.from_publication_id != expected_publication_id
            or event.from_revision != expected_revision
        ):
            raise BigQueryPublicationError(
                "activation event contradicts its expected active pointer"
            )
        active = self._table("active_publications")
        manifests = self._table("publication_manifests")
        deltas = self._table("publication_membership_deltas")
        versions = self._table("publication_result_versions")
        inventories = self._table("publication_candidate_inventory")
        activations = self._table("publication_activations")
        rows = self._query(
            f"""-- claimsflow:compare_and_swap_active_publication
DECLARE current_publication_id STRING;
DECLARE current_revision INT64;

BEGIN TRANSACTION;
ASSERT (
  SELECT COUNT(*) = 1 FROM {active} WHERE environment = @environment
) AS 'active publication control row is missing or not unique';
SET current_publication_id = (
  SELECT ANY_VALUE(publication_id) FROM {active} WHERE environment = @environment
);
SET current_revision = COALESCE((
  SELECT ANY_VALUE(revision) FROM {active} WHERE environment = @environment
), 0);

ASSERT current_revision = @expected_revision
  AND current_publication_id IS NOT DISTINCT FROM @expected_publication_id
AS 'active publication compare-and-swap conflict';

ASSERT (
  SELECT COUNT(*) = 1
  FROM {manifests}
  WHERE publication_id = @to_publication_id
    AND environment = @environment
) AS 'activation target manifest does not exist in this environment';

ASSERT (
  SELECT
    COUNT(*) > 0
    AND COUNTIF(
      REGEXP_CONTAINS(
        JSON_VALUE(manifest_json, '$.dbt_validation_selection_fingerprint'),
        r'^[0-9a-f]{{32}}$'
      ) IS DISTINCT FROM TRUE
      OR REGEXP_CONTAINS(
        JSON_VALUE(manifest_json, '$.dbt_candidate_build_fingerprint'),
        r'^[0-9a-f]{{32}}$'
      ) IS DISTINCT FROM TRUE
      OR REGEXP_CONTAINS(
        JSON_VALUE(manifest_json, '$.code_commit'),
        r'^[0-9a-f]{{40}}$'
      ) IS DISTINCT FROM TRUE
      OR JSON_VALUE(manifest_json, '$.dbt_candidate_build_fingerprint') IS DISTINCT FROM
        LOWER(TO_HEX(MD5(CONCAT(
          'candidate-build-v1\n',
          publication_id,
          '\n',
          JSON_VALUE(manifest_json, '$.dbt_validation_selection_fingerprint'),
          '\n',
          JSON_VALUE(manifest_json, '$.code_commit')
        ))))
      OR ENDS_WITH(
        JSON_VALUE(relation, '$.candidate_relation'),
        CONCAT(
          '__', publication_id,
          '__', JSON_VALUE(manifest_json, '$.dbt_validation_selection_fingerprint'),
          '__', JSON_VALUE(manifest_json, '$.dbt_candidate_build_fingerprint')
        )
      ) IS DISTINCT FROM TRUE
    ) = 0
  FROM {manifests}
  CROSS JOIN UNNEST(JSON_QUERY_ARRAY(manifest_json, '$.published_relations')) AS relation
  WHERE publication_id = @to_publication_id
    AND environment = @environment
) AS 'activation target physical relations are not bound to exact selection and code';

ASSERT COALESCE((
  SELECT
    ARRAY_LENGTH(membership_delta_chain) BETWEEN 1 AND @max_membership_chain_depth
    AND membership_delta_chain[SAFE_OFFSET(ARRAY_LENGTH(membership_delta_chain) - 1)] =
      @to_publication_id
    AND ARRAY_LENGTH(membership_delta_chain) = (
      SELECT COUNT(DISTINCT chain_publication_id)
      FROM UNNEST(membership_delta_chain) AS chain_publication_id
    )
    AND (
      (
        membership_mode = 'base'
        AND membership_delta_chain = [@to_publication_id]
      )
      OR (
        membership_mode = 'delta'
        AND (
          (
            parent_publication_id IS NULL
            AND membership_delta_chain = [@to_publication_id]
          )
          OR (
            parent_publication_id IS NOT NULL
            AND ARRAY_LENGTH(membership_delta_chain) >= 2
            AND membership_delta_chain[
              SAFE_OFFSET(ARRAY_LENGTH(membership_delta_chain) - 2)
            ] = parent_publication_id
          )
        )
      )
    )
  FROM {manifests}
  WHERE publication_id = @to_publication_id
    AND environment = @environment
), FALSE) AS 'activation target manifest chain shape is invalid';

ASSERT (
  SELECT
    COUNTIF(JSON_VALUE(gate, '$.status') IS DISTINCT FROM 'passed') = 0
    AND COUNT(DISTINCT IF(
      JSON_VALUE(gate, '$.name') IN (
        'validation',
        'dbt_build',
        'freshness',
        'row_reconciliation',
        'financial_reconciliation'
      ),
      JSON_VALUE(gate, '$.name'),
      NULL
    )) = 5
  FROM {manifests} AS manifest
  CROSS JOIN UNNEST(JSON_QUERY_ARRAY(manifest.manifest_json, '$.gate_results')) AS gate
  WHERE manifest.publication_id = @to_publication_id
    AND manifest.environment = @environment
) AS 'activation target has missing or failed publication gates';

ASSERT (
  SELECT COUNTIF(
    CAST(JSON_VALUE(reconciliation, '$.reconciled') AS BOOL) IS NOT TRUE
  ) = 0
  FROM {manifests} AS manifest
  CROSS JOIN UNNEST(
    ARRAY_CONCAT(
      JSON_QUERY_ARRAY(manifest.manifest_json, '$.row_reconciliations'),
      JSON_QUERY_ARRAY(manifest.manifest_json, '$.financial_reconciliations')
    )
  ) AS reconciliation
  WHERE manifest.publication_id = @to_publication_id
    AND manifest.environment = @environment
) AS 'activation target contains an unreconciled control';

ASSERT (
  WITH target AS (
    SELECT membership_delta_chain
    FROM {manifests}
    WHERE publication_id = @to_publication_id
      AND environment = @environment
  ),
  chain AS (
    SELECT
      chain_publication_id,
      chain_position,
      membership_delta_chain[SAFE_OFFSET(chain_position - 1)] AS expected_parent_publication_id
    FROM target
    CROSS JOIN UNNEST(membership_delta_chain) AS chain_publication_id WITH OFFSET chain_position
  )
  SELECT COUNT(*) = 0
  FROM (
    SELECT chain.chain_position
    FROM chain
    LEFT JOIN {manifests} AS chain_manifest
      ON chain.chain_publication_id = chain_manifest.publication_id
      AND chain_manifest.environment = @environment
    GROUP BY chain.chain_position, chain.expected_parent_publication_id
    HAVING COUNT(chain_manifest.publication_id) != 1
      OR COUNTIF(
        chain.chain_position > 0
        AND chain_manifest.parent_publication_id IS DISTINCT FROM
          chain.expected_parent_publication_id
      ) > 0
  )
) AS 'activation target has a missing, duplicate, or broken manifest chain';

ASSERT NOT EXISTS (
  SELECT 1
  FROM {inventories}
  WHERE publication_id = @to_publication_id
  GROUP BY logical_relation, business_key
  HAVING COUNT(*) != 1
) AS 'activation target inventory contains duplicate business keys';

ASSERT NOT EXISTS (
  SELECT 1
  FROM {inventories}
  WHERE publication_id = @to_publication_id
  GROUP BY inventory_sequence
  HAVING COUNT(*) != 1
) AS 'activation target inventory contains duplicate sequence values';

ASSERT (
  WITH declared AS (
    SELECT
      JSON_VALUE(relation_inventory, '$.logical_relation') AS logical_relation,
      CAST(JSON_VALUE(relation_inventory, '$.row_count') AS INT64) AS row_count,
      JSON_VALUE(relation_inventory, '$.inventory_sha256') AS inventory_sha256
    FROM {manifests} AS manifest
    CROSS JOIN UNNEST(
      JSON_QUERY_ARRAY(manifest.manifest_json, '$.relation_inventories')
    ) AS relation_inventory
    WHERE manifest.publication_id = @to_publication_id
      AND manifest.environment = @environment
  ),
  actual AS (
    SELECT
      logical_relation,
      COUNT(*) AS row_count,
      LOWER(TO_HEX(SHA256(STRING_AGG(
        FORMAT('%08x:%s:%s', BYTE_LENGTH(business_key), business_key, result_sha256),
        '' ORDER BY inventory_sequence
      )))) AS inventory_sha256
    FROM {inventories}
    WHERE publication_id = @to_publication_id
    GROUP BY logical_relation
  )
  SELECT COUNT(*) = 0
  FROM declared
  FULL OUTER JOIN actual USING (logical_relation)
  WHERE declared.row_count IS DISTINCT FROM COALESCE(actual.row_count, 0)
    OR declared.inventory_sha256 IS DISTINCT FROM
      COALESCE(actual.inventory_sha256, LOWER(TO_HEX(SHA256(''))))
) AS 'activation target inventory contradicts its manifest commitment';

ASSERT (
  WITH target AS (
    SELECT membership_delta_chain
    FROM {manifests}
    WHERE publication_id = @to_publication_id
      AND environment = @environment
  ),
  chain AS (
    SELECT chain_publication_id, chain_position
    FROM target
    CROSS JOIN UNNEST(membership_delta_chain) AS chain_publication_id WITH OFFSET chain_position
  ),
  ranked AS (
    SELECT
      delta.logical_relation,
      delta.business_key,
      delta.result_version_id,
      delta.tombstone,
      ROW_NUMBER() OVER (
        PARTITION BY delta.logical_relation, delta.business_key
        ORDER BY chain.chain_position DESC, delta.sequence DESC
      ) AS membership_precedence
    FROM chain
    JOIN {deltas} AS delta
      ON chain.chain_publication_id = delta.publication_id
  ),
  resolved AS (
    SELECT logical_relation, business_key, result_version_id
    FROM ranked
    WHERE membership_precedence = 1
      AND NOT tombstone
  ),
  resolved_content AS (
    SELECT
      resolved.logical_relation,
      resolved.business_key,
      result_version.result_sha256
    FROM resolved
    LEFT JOIN {versions} AS result_version
      ON resolved.result_version_id = result_version.result_version_id
      AND resolved.logical_relation = result_version.logical_relation
      AND resolved.business_key = result_version.business_key
  ),
  expected AS (
    SELECT logical_relation, business_key, result_sha256
    FROM {inventories}
    WHERE publication_id = @to_publication_id
  )
  SELECT COUNT(*) = 0
  FROM resolved_content
  FULL OUTER JOIN expected
    USING (logical_relation, business_key)
  WHERE resolved_content.result_sha256 IS DISTINCT FROM expected.result_sha256
) AS 'activation target membership does not exactly match its complete inventory';

ASSERT NOT EXISTS (
  SELECT 1
  FROM {deltas} AS delta
  JOIN {versions} AS result_version
    ON delta.result_version_id = result_version.result_version_id
  JOIN {manifests} AS target
    ON target.publication_id = @to_publication_id
    AND target.environment = @environment
  LEFT JOIN {manifests} AS source_manifest
    ON source_manifest.publication_id = result_version.source_publication_id
    AND source_manifest.environment = @environment
  WHERE delta.publication_id IN UNNEST(target.membership_delta_chain)
    AND NOT delta.tombstone
    AND (
      source_manifest.publication_id IS NULL
      OR (
        result_version.source_publication_id != @to_publication_id
        AND NOT EXISTS (
          SELECT 1
          FROM {activations} AS trusted_activation
          WHERE trusted_activation.environment = @environment
            AND trusted_activation.to_publication_id = result_version.source_publication_id
        )
      )
    )
) AS 'activation target references an untrusted result-version source';

ASSERT @kind != 'rollback' OR EXISTS (
  SELECT 1
  FROM {activations}
  WHERE environment = @environment
    AND to_publication_id = @to_publication_id
) AS 'rollback target was never previously active';

UPDATE {active}
SET
  publication_id = @to_publication_id,
  revision = @to_revision,
  updated_at_utc = @activated_at_utc
WHERE environment = @environment
  AND revision = @expected_revision
  AND publication_id IS NOT DISTINCT FROM @expected_publication_id;
ASSERT @@row_count = 1 AS 'active publication compare-and-swap conflict';

INSERT INTO {activations} (
  event_id,
  kind,
  environment,
  from_publication_id,
  to_publication_id,
  from_revision,
  to_revision,
  reason,
  activated_at_utc
)
VALUES (
  @event_id,
  @kind,
  @environment,
  @expected_publication_id,
  @to_publication_id,
  @expected_revision,
  @to_revision,
  @reason,
  @activated_at_utc
);
COMMIT TRANSACTION;

SELECT environment, publication_id, revision, updated_at_utc
FROM {active}
WHERE environment = @environment;
""",
            {
                "event_id": ("STRING", event.event_id),
                "kind": ("STRING", event.kind),
                "environment": ("STRING", event.environment),
                "expected_publication_id": ("STRING", expected_publication_id),
                "expected_revision": ("INT64", expected_revision),
                "to_publication_id": ("STRING", event.to_publication_id),
                "to_revision": ("INT64", event.to_revision),
                "max_membership_chain_depth": (
                    "INT64",
                    self._max_membership_chain_depth,
                ),
                "reason": ("STRING", event.reason),
                "activated_at_utc": ("TIMESTAMP", event.activated_at_utc),
            },
        )
        if len(rows) != 1:
            raise BigQueryPublicationError("active pointer update returned no unique state")
        row = rows[0]
        updated = row["updated_at_utc"]
        if not isinstance(updated, datetime):
            raise BigQueryPublicationError("updated active pointer timestamp is malformed")
        return ActivePublication(
            environment=cast(PublicationEnvironment, str(row["environment"])),
            publication_id=str(row["publication_id"]),
            revision=int(cast(int, row["revision"])),
            updated_at_utc=updated,
        )

    def was_activated(
        self,
        environment: PublicationEnvironment,
        publication_id: str,
    ) -> bool:
        rows = self._query(
            f"""-- claimsflow:was_publication_activated
SELECT COUNT(*) > 0 AS was_activated
FROM {self._table("publication_activations")}
WHERE environment = @environment
  AND to_publication_id = @publication_id
""",
            {
                "environment": ("STRING", environment),
                "publication_id": ("STRING", publication_id),
            },
        )
        if len(rows) != 1:
            raise BigQueryPublicationError("activation history query returned no unique result")
        return bool(rows[0]["was_activated"])
