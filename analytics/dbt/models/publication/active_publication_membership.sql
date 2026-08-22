{{
  config(
    materialized='view',
    schema='curated',
    tags=['publication_control', 'phase4b3'],
    contract={'enforced': true}
  )
}}

with active_manifest as (
  select
    active.environment,
    active.publication_id as active_publication_id,
    active.revision as active_revision,
    manifest.membership_delta_chain
  from {{ source('publication_control', 'active_publications') }} as active
  inner join {{ source('publication_control', 'publication_manifests') }} as manifest
    on active.publication_id = manifest.publication_id
    and active.environment = manifest.environment
),

ordered_chain as (
  select
    environment,
    active_publication_id,
    active_revision,
    mapping_publication_id,
    chain_position
  from active_manifest
  cross join unnest(membership_delta_chain) as mapping_publication_id with offset as chain_position
),

ranked_membership as (
  select
    chain.environment,
    chain.active_publication_id,
    chain.active_revision,
    delta.publication_id as mapping_publication_id,
    delta.logical_relation,
    delta.business_key,
    delta.result_version_id,
    delta.tombstone,
    row_number() over (
      partition by chain.environment, delta.logical_relation, delta.business_key
      order by chain.chain_position desc, delta.sequence desc
    ) as membership_precedence
  from ordered_chain as chain
  inner join {{ source('publication_control', 'publication_membership_deltas') }} as delta
    on chain.mapping_publication_id = delta.publication_id
),

latest_membership as (
  select * except (membership_precedence)
  from ranked_membership
  where membership_precedence = 1
    and not tombstone
)

select
  membership.environment,
  membership.active_publication_id,
  membership.active_revision,
  membership.mapping_publication_id,
  membership.logical_relation,
  membership.business_key,
  membership.result_version_id,
  result_version.source_publication_id as result_source_publication_id,
  result_version.result_sha256,
  result_version.physical_relation
from latest_membership as membership
inner join {{ source('publication_control', 'publication_result_versions') }} as result_version
  on membership.result_version_id = result_version.result_version_id
  and membership.logical_relation = result_version.logical_relation
  and membership.business_key = result_version.business_key

