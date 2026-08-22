with requested_validation_ids as (
  {% for validation_id in claimsflow_validation_ids() %}
  select '{{ validation_id }}' as validation_id
  {% if not loop.last %}union all{% endif %}
  {% endfor %}
),

audit_evidence as (
  select
    validation_id,
    count(*) as audit_row_count,
    countif(
      synthetic_only is true
      and publication_allowed is true
      and reconciled is true
      and decision = 'approved'
    ) as approved_row_count
  from {{ source('claimsflow_audit', 'quality_runs') }}
  where {{ claimsflow_validation_filter('validation_id') }}
  group by validation_id
)

select
  requested.validation_id,
  coalesce(audit.audit_row_count, 0) as audit_row_count,
  coalesce(audit.approved_row_count, 0) as approved_row_count
from requested_validation_ids as requested
left join audit_evidence as audit using (validation_id)
where coalesce(audit.audit_row_count, 0) != 1
  or coalesce(audit.approved_row_count, 0) != 1
{{ config(tags=['validated_staging', 'phase4a']) }}
