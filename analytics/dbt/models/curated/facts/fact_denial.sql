{{
  config(
    partition_by={"field": "denial_date", "data_type": "date", "granularity": "month"},
    cluster_by=["payer_dimension_id", "denial_reason_dimension_id", "denial_status"]
  )
}}

with denials as (
  select *
  from {{ ref('stg_denials') }}
),

resolved as (
  select
    denial.*,
    claim.claim_fact_id,
    claim_line.claim_line_fact_id,
    payer.payer_dimension_id,
    denial_reason.denial_reason_dimension_id
  from denials as denial
  left join {{ ref('fact_claim') }} as claim
    on denial.candidate_publication_id = claim.candidate_publication_id
    and denial.candidate_selection_fingerprint = claim.candidate_selection_fingerprint
    and denial.claim_source_system = claim.source_system
    and denial.claim_id = claim.claim_id
    and denial.claim_submission_sequence = claim.submission_sequence
  left join {{ ref('fact_claim_line') }} as claim_line
    on denial.candidate_publication_id = claim_line.candidate_publication_id
    and denial.candidate_selection_fingerprint = claim_line.candidate_selection_fingerprint
    and denial.claim_source_system = claim_line.source_system
    and denial.claim_id = claim_line.claim_id
    and denial.claim_submission_sequence = claim_line.submission_sequence
    and denial.claim_line_number = claim_line.line_number
  left join {{ ref('dim_payer') }} as payer
    on denial.candidate_publication_id = payer.candidate_publication_id
    and denial.candidate_selection_fingerprint = payer.candidate_selection_fingerprint
    and denial.payer_id = payer.payer_id
    and denial.denial_date >= payer.valid_from
    and (payer.valid_to is null or denial.denial_date < payer.valid_to)
  left join {{ ref('dim_denial_reason') }} as denial_reason
    on denial.candidate_publication_id = denial_reason.candidate_publication_id
    and denial.candidate_selection_fingerprint = denial_reason.candidate_selection_fingerprint
    and denial.denial_reason_code = denial_reason.denial_reason_code
    and denial.denial_date >= denial_reason.valid_from
    and (denial_reason.valid_to is null or denial.denial_date < denial_reason.valid_to)
)

select
  candidate_publication_id,
  candidate_selection_fingerprint,
  {{
    claimsflow_fact_key(
      'denial',
      [('source_system', 'source_system'), ('denial_id', 'denial_id')]
    )
  }} as denial_fact_id,
  claim_fact_id,
  claim_line_fact_id,
  payer_dimension_id,
  denial_reason_dimension_id,
  {{ claimsflow_date_dimension_id('denial_date') }} as denial_date_dimension_id,
  {{ claimsflow_date_dimension_id('received_at') }} as received_date_dimension_id,
  {{ claimsflow_date_dimension_id('filing_deadline_date') }} as filing_deadline_date_dimension_id,
  {{ claimsflow_date_dimension_id('appeal_deadline_date') }} as appeal_deadline_date_dimension_id,
  source_system,
  denial_id,
  claim_source_system,
  claim_id,
  claim_submission_sequence,
  claim_line_number,
  claim_line_id,
  payer_id,
  denial_reason_code,
  denial_category,
  denial_date,
  received_at,
  denied_amount,
  currency_code,
  filing_deadline_date,
  appeal_deadline_date,
  denial_status,
  preventable_flag,
  documentation_ready_flag,
  missing_document_codes,
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
