{{ config(tags=['publication_control', 'phase4b3']) }}

with control_environment as (
  select environment
  from unnest(['local', 'dev-demo']) as environment
  union distinct
  select environment
  from {{ source('publication_control', 'active_publications') }}
),

duplicate_active_pointer as (
  select
    'duplicate_active_pointer' as failure,
    control.environment as identity
  from control_environment as control
  left join {{ source('publication_control', 'active_publications') }} as active
    on control.environment = active.environment
  group by control.environment
  having count(active.environment) != 1
    or control.environment not in ('local', 'dev-demo')
),

duplicate_manifest_id as (
  select
    'duplicate_manifest_id' as failure,
    publication_id as identity
  from {{ source('publication_control', 'publication_manifests') }}
  group by publication_id
  having count(*) != 1
),

active_manifest as (
  select
    active.environment,
    active.publication_id,
    manifest.parent_publication_id,
    manifest.membership_delta_chain,
    manifest.membership_mode,
    manifest.manifest_json
  from {{ source('publication_control', 'active_publications') }} as active
  left join {{ source('publication_control', 'publication_manifests') }} as manifest
    on active.publication_id = manifest.publication_id
    and active.environment = manifest.environment
  where active.publication_id is not null
),

invalid_active_manifest as (
  select
    'invalid_active_manifest' as failure,
    concat(environment, ':', publication_id) as identity
  from active_manifest
  where membership_delta_chain is null
    or array_length(membership_delta_chain) = 0
    or array_length(membership_delta_chain) > 8
    or membership_delta_chain[safe_offset(array_length(membership_delta_chain) - 1)]
      != publication_id
    or array_length(membership_delta_chain) != (
      select count(distinct chain_publication_id)
      from unnest(ifnull(membership_delta_chain, array<string>[])) as chain_publication_id
    )
    or coalesce(not (
      (
        membership_mode = 'base'
        and membership_delta_chain = [publication_id]
      )
      or (
        membership_mode = 'delta'
        and (
          (
            parent_publication_id is null
            and membership_delta_chain = [publication_id]
          )
          or (
            parent_publication_id is not null
            and array_length(membership_delta_chain) >= 2
            and membership_delta_chain[
              safe_offset(array_length(membership_delta_chain) - 2)
            ] = parent_publication_id
          )
        )
      )
    ), true)
),

active_chain as (
  select
    active.environment,
    active.publication_id as active_publication_id,
    chain_publication_id,
    chain_position,
    active.membership_delta_chain[safe_offset(chain_position - 1)]
      as expected_parent_publication_id
  from active_manifest as active
  cross join unnest(ifnull(active.membership_delta_chain, array<string>[]))
    as chain_publication_id with offset as chain_position
),

broken_active_chain as (
  select
    'broken_active_chain' as failure,
    concat(chain.environment, ':', chain.active_publication_id, ':', chain.chain_publication_id)
      as identity
  from active_chain as chain
  left join {{ source('publication_control', 'publication_manifests') }} as chain_manifest
    on chain.chain_publication_id = chain_manifest.publication_id
    and chain.environment = chain_manifest.environment
  group by
    chain.environment,
    chain.active_publication_id,
    chain.chain_publication_id,
    chain.chain_position,
    chain.expected_parent_publication_id
  having count(chain_manifest.publication_id) != 1
    or countif(
      chain.chain_position > 0
      and chain_manifest.parent_publication_id is distinct from
        chain.expected_parent_publication_id
    ) > 0
),

failed_active_gate as (
  select
    'failed_active_gate' as failure,
    concat(manifest.environment, ':', manifest.publication_id, ':', json_value(gate, '$.name'))
      as identity
  from active_manifest as manifest
  cross join unnest(json_query_array(manifest.manifest_json, '$.gate_results')) as gate
  where json_value(gate, '$.status') is distinct from 'passed'
),

required_gate as (
  select gate_name
  from unnest([
    'validation',
    'dbt_build',
    'freshness',
    'row_reconciliation',
    'financial_reconciliation'
  ]) as gate_name
),

missing_active_gate as (
  select
    'missing_active_gate' as failure,
    concat(manifest.environment, ':', manifest.publication_id, ':', required.gate_name)
      as identity
  from active_manifest as manifest
  cross join required_gate as required
  where not exists (
    select 1
    from unnest(json_query_array(manifest.manifest_json, '$.gate_results')) as gate
    where json_value(gate, '$.name') = required.gate_name
  )
),

duplicate_delta_key as (
  select
    'duplicate_delta_key' as failure,
    concat(publication_id, ':', logical_relation, ':', business_key) as identity
  from {{ source('publication_control', 'publication_membership_deltas') }}
  group by publication_id, logical_relation, business_key
  having count(*) != 1
),

duplicate_result_version as (
  select
    'duplicate_result_version' as failure,
    result_version_id as identity
  from {{ source('publication_control', 'publication_result_versions') }}
  group by result_version_id
  having count(*) != 1
),

duplicate_inventory_key as (
  select
    'duplicate_inventory_key' as failure,
    concat(publication_id, ':', logical_relation, ':', business_key) as identity
  from {{ source('publication_control', 'publication_candidate_inventory') }}
  group by publication_id, logical_relation, business_key
  having count(*) != 1
),

duplicate_inventory_sequence as (
  select
    'duplicate_inventory_sequence' as failure,
    concat(publication_id, ':', cast(inventory_sequence as string)) as identity
  from {{ source('publication_control', 'publication_candidate_inventory') }}
  group by publication_id, inventory_sequence
  having count(*) != 1
),

orphan_membership as (
  select
    'orphan_membership' as failure,
    concat(delta.publication_id, ':', delta.logical_relation, ':', delta.business_key) as identity
  from {{ source('publication_control', 'publication_membership_deltas') }} as delta
  left join {{ source('publication_control', 'publication_result_versions') }} as result_version
    on delta.result_version_id = result_version.result_version_id
    and delta.logical_relation = result_version.logical_relation
    and delta.business_key = result_version.business_key
  where not delta.tombstone
    and result_version.result_version_id is null
),

duplicate_resolved_key as (
  select
    'duplicate_resolved_key' as failure,
    concat(environment, ':', logical_relation, ':', business_key) as identity
  from {{ ref('active_publication_membership') }}
  group by environment, logical_relation, business_key
  having count(*) != 1
),

untrusted_result_source as (
  select
    'untrusted_result_source' as failure,
    concat(
      resolved.environment,
      ':',
      resolved.logical_relation,
      ':',
      resolved.business_key,
      ':',
      resolved.result_source_publication_id
    ) as identity
  from {{ ref('active_publication_membership') }} as resolved
  where not exists (
    select 1
    from {{ source('publication_control', 'publication_activations') }} as activation
    where activation.environment = resolved.environment
      and activation.to_publication_id = resolved.result_source_publication_id
  )
),

expected_active_inventory as (
  select
    active.environment,
    inventory.logical_relation,
    inventory.business_key,
    inventory.result_sha256
  from {{ source('publication_control', 'active_publications') }} as active
  inner join {{ source('publication_control', 'publication_candidate_inventory') }} as inventory
    on active.publication_id = inventory.publication_id
  where active.publication_id is not null
),

active_inventory_mismatch as (
  select
    'active_inventory_mismatch' as failure,
    concat(
      coalesce(resolved.environment, expected.environment),
      ':',
      coalesce(resolved.logical_relation, expected.logical_relation),
      ':',
      coalesce(resolved.business_key, expected.business_key)
    ) as identity
  from {{ ref('active_publication_membership') }} as resolved
  full outer join expected_active_inventory as expected
    using (environment, logical_relation, business_key)
  where resolved.result_sha256 is distinct from expected.result_sha256
)

select * from duplicate_active_pointer
union all
select * from duplicate_manifest_id
union all
select * from invalid_active_manifest
union all
select * from broken_active_chain
union all
select * from failed_active_gate
union all
select * from missing_active_gate
union all
select * from duplicate_delta_key
union all
select * from duplicate_result_version
union all
select * from duplicate_inventory_key
union all
select * from duplicate_inventory_sequence
union all
select * from orphan_membership
union all
select * from duplicate_resolved_key
union all
select * from untrusted_result_source
union all
select * from active_inventory_mismatch
