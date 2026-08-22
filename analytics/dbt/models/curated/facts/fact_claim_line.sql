{{
  config(
    partition_by={"field": "service_from_date", "data_type": "date", "granularity": "month"},
    cluster_by=["claim_fact_id", "procedure_dimension_id", "line_status"]
  )
}}

with lines as (
  select *
  from {{ ref('stg_claim_lines') }}
),

line_diagnosis_codes as (
  select
    line.candidate_publication_id,
    line.candidate_selection_fingerprint,
    line.validated_record_id,
    line.diagnosis_code_system,
    line.service_from_date,
    diagnosis_code,
    diagnosis_offset
  from lines as line
  cross join unnest(line.diagnosis_codes) as diagnosis_code with offset as diagnosis_offset
),

diagnosis_resolutions as (
  select
    code.candidate_publication_id,
    code.candidate_selection_fingerprint,
    code.validated_record_id,
    array_agg(
      coalesce(diagnosis.diagnosis_dimension_id, '__unresolved_dimension__')
      order by code.diagnosis_offset
    ) as diagnosis_dimension_ids
  from line_diagnosis_codes as code
  left join {{ ref('dim_diagnosis') }} as diagnosis
    on code.candidate_publication_id = diagnosis.candidate_publication_id
    and code.candidate_selection_fingerprint = diagnosis.candidate_selection_fingerprint
    and code.diagnosis_code_system = diagnosis.code_system
    and code.diagnosis_code = diagnosis.diagnosis_code
    and code.service_from_date >= diagnosis.valid_from
    and (diagnosis.valid_to is null or code.service_from_date < diagnosis.valid_to)
  group by
    code.candidate_publication_id,
    code.candidate_selection_fingerprint,
    code.validated_record_id
),

resolved as (
  select
    line.*,
    claim.claim_fact_id,
    procedure.procedure_dimension_id,
    denial_reason.denial_reason_dimension_id,
    diagnosis_resolutions.diagnosis_dimension_ids
  from lines as line
  left join {{ ref('fact_claim') }} as claim
    on line.candidate_publication_id = claim.candidate_publication_id
    and line.candidate_selection_fingerprint = claim.candidate_selection_fingerprint
    and line.source_system = claim.source_system
    and line.claim_id = claim.claim_id
    and line.submission_sequence = claim.submission_sequence
  left join {{ ref('dim_procedure') }} as procedure
    on line.candidate_publication_id = procedure.candidate_publication_id
    and line.candidate_selection_fingerprint = procedure.candidate_selection_fingerprint
    and line.procedure_code_system = procedure.code_system
    and line.procedure_code = procedure.procedure_code
    and line.service_from_date >= procedure.valid_from
    and (procedure.valid_to is null or line.service_from_date < procedure.valid_to)
  left join {{ ref('dim_denial_reason') }} as denial_reason
    on line.candidate_publication_id = denial_reason.candidate_publication_id
    and line.candidate_selection_fingerprint = denial_reason.candidate_selection_fingerprint
    and line.denial_reason_code = denial_reason.denial_reason_code
    and line.service_from_date >= denial_reason.valid_from
    and (denial_reason.valid_to is null or line.service_from_date < denial_reason.valid_to)
  left join diagnosis_resolutions
    on line.candidate_publication_id = diagnosis_resolutions.candidate_publication_id
    and line.candidate_selection_fingerprint = diagnosis_resolutions.candidate_selection_fingerprint
    and line.validated_record_id = diagnosis_resolutions.validated_record_id
)

select
  candidate_publication_id,
  candidate_selection_fingerprint,
  {{
    claimsflow_fact_key(
      'claim_line',
      [
        ('source_system', 'source_system'),
        ('claim_id', 'claim_id'),
        ('submission_sequence', 'submission_sequence'),
        ('line_number', 'line_number')
      ]
    )
  }} as claim_line_fact_id,
  claim_fact_id,
  procedure_dimension_id,
  coalesce(diagnosis_dimension_ids, cast([] as array<string>)) as diagnosis_dimension_ids,
  denial_reason_dimension_id,
  {{ claimsflow_date_dimension_id('service_from_date') }} as service_from_date_dimension_id,
  {{ claimsflow_date_dimension_id('service_to_date') }} as service_to_date_dimension_id,
  source_system,
  claim_id,
  submission_sequence,
  line_number,
  claim_line_id,
  service_from_date,
  service_to_date,
  procedure_code,
  procedure_code_system,
  procedure_modifiers,
  diagnosis_codes,
  diagnosis_code_system,
  place_of_service_code,
  revenue_code,
  units,
  line_status,
  denial_reason_code,
  billed_amount,
  allowed_amount,
  payer_paid_amount,
  patient_paid_amount,
  patient_responsibility_amount,
  adjustment_amount,
  outstanding_balance,
  currency_code,
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
