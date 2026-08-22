with plan_history as (
  {{
    claimsflow_effective_dimension(
      entity_name='plan',
      source_model='stg_reference_plans',
      business_keys=['plan_id'],
      attributes=['payer_id', 'plan_name', 'coverage_type']
    )
  }}
),

payer_history as (
  select
    candidate_publication_id,
    candidate_selection_fingerprint,
    payer_dimension_id,
    source_system,
    payer_id,
    valid_from,
    valid_to
  from {{ ref('dim_payer') }}
)

select
  plan_history.candidate_publication_id,
  plan_history.candidate_selection_fingerprint,
  plan_history.plan_dimension_id,
  plan_history.plan_business_key,
  payer_history.payer_dimension_id,
  plan_history.source_system,
  plan_history.plan_id,
  plan_history.payer_id,
  plan_history.plan_name,
  plan_history.coverage_type,
  plan_history.valid_from,
  plan_history.valid_to,
  plan_history.source_active_flag,
  plan_history.is_current,
  plan_history.source_validated_record_id,
  plan_history.source_validation_id,
  plan_history.source_batch_id,
  plan_history.quality_report_sha256,
  plan_history.quality_configuration_sha256,
  plan_history.validated_record_set_sha256,
  plan_history.synthetic_only
from plan_history
left join payer_history
  on plan_history.candidate_publication_id = payer_history.candidate_publication_id
  and plan_history.candidate_selection_fingerprint
    = payer_history.candidate_selection_fingerprint
  and plan_history.source_system = payer_history.source_system
  and plan_history.payer_id = payer_history.payer_id
  and plan_history.valid_from >= payer_history.valid_from
  and coalesce(plan_history.valid_to, date '9999-12-31')
    <= coalesce(payer_history.valid_to, date '9999-12-31')
