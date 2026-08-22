select
  plan.plan_dimension_id,
  plan.payer_dimension_id,
  plan.source_system,
  plan.payer_id,
  plan.valid_from,
  plan.valid_to
from {{ ref('dim_plan') }} as plan
left join {{ ref('dim_payer') }} as payer
  on plan.candidate_publication_id = payer.candidate_publication_id
  and plan.candidate_selection_fingerprint = payer.candidate_selection_fingerprint
  and plan.payer_dimension_id = payer.payer_dimension_id
  and plan.source_system = payer.source_system
  and plan.payer_id = payer.payer_id
  and plan.valid_from >= payer.valid_from
  and coalesce(plan.valid_to, date '9999-12-31')
    <= coalesce(payer.valid_to, date '9999-12-31')
where payer.payer_dimension_id is null
