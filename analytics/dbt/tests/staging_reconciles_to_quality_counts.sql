with approved_quality_runs as (
  select
    validation_id,
    batch_id,
    accepted + warned as expected_validated_rows
  from {{ source('claimsflow_audit', 'quality_runs') }}
  where synthetic_only is true
    and publication_allowed is true
    and reconciled is true
    and decision = 'approved'
    and {{ claimsflow_validation_filter('validation_id') }}
),

staged_counts as (
  select validation_id, batch_id, count(*) as actual_validated_rows
  from {{ ref('stg_validated_records') }}
  group by validation_id, batch_id
)

select
  coalesce(quality.validation_id, staged.validation_id) as validation_id,
  coalesce(quality.batch_id, staged.batch_id) as batch_id,
  quality.expected_validated_rows,
  staged.actual_validated_rows
from approved_quality_runs as quality
full outer join staged_counts as staged
  on quality.validation_id = staged.validation_id
  and quality.batch_id = staged.batch_id
where quality.validation_id is null
  or staged.validation_id is null
  or quality.expected_validated_rows != staged.actual_validated_rows
{{ config(tags=['validated_staging', 'phase4a']) }}
