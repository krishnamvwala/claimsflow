{{
  config(
    partition_by={"field": "created_at", "data_type": "timestamp", "granularity": "month"},
    cluster_by=["denial_fact_id", "claim_fact_id", "appeal_status"]
  )
}}

with appeals as (
  select *
  from {{ ref('stg_appeals') }}
),

resolved as (
  select
    appeal.*,
    denial.denial_fact_id,
    claim.claim_fact_id
  from appeals as appeal
  left join {{ ref('fact_denial') }} as denial
    on appeal.candidate_publication_id = denial.candidate_publication_id
    and appeal.candidate_selection_fingerprint = denial.candidate_selection_fingerprint
    and appeal.denial_source_system = denial.source_system
    and appeal.denial_id = denial.denial_id
  left join {{ ref('fact_claim') }} as claim
    on appeal.candidate_publication_id = claim.candidate_publication_id
    and appeal.candidate_selection_fingerprint = claim.candidate_selection_fingerprint
    and appeal.claim_source_system = claim.source_system
    and appeal.claim_id = claim.claim_id
    and appeal.claim_submission_sequence = claim.submission_sequence
)

select
  candidate_publication_id,
  candidate_selection_fingerprint,
  {{
    claimsflow_fact_key(
      'appeal',
      [('source_system', 'source_system'), ('appeal_id', 'appeal_id')]
    )
  }} as appeal_fact_id,
  denial_fact_id,
  claim_fact_id,
  {{ claimsflow_date_dimension_id('created_at') }} as created_date_dimension_id,
  {{ claimsflow_date_dimension_id('filed_at') }} as filed_date_dimension_id,
  {{ claimsflow_date_dimension_id('appeal_deadline_date') }} as appeal_deadline_date_dimension_id,
  {{ claimsflow_date_dimension_id('decision_date') }} as decision_date_dimension_id,
  source_system,
  appeal_id,
  denial_source_system,
  denial_id,
  claim_source_system,
  claim_id,
  claim_submission_sequence,
  appeal_level,
  appeal_status,
  created_at,
  filed_at,
  appeal_deadline_date,
  decision_date,
  outcome,
  requested_amount,
  recovered_amount,
  currency_code,
  documentation_ready_flag,
  owner_queue,
  source_updated_at,
  validated_record_id as source_validated_record_id,
  validation_id as source_validation_id,
  batch_id as source_batch_id,
  disposition as source_disposition,
  quality_report_sha256,
  quality_configuration_sha256,
  validated_record_set_sha256,
  synthetic_only
from resolved
