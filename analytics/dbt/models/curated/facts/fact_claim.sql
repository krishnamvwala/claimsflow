{{
  config(
    partition_by={"field": "service_from_date", "data_type": "date", "granularity": "month"},
    cluster_by=["payer_dimension_id", "facility_dimension_id", "claim_status"]
  )
}}

with claims as (
  select *
  from {{ ref('stg_claims') }}
),

resolved as (
  select
    claim.*,
    patient.patient_dimension_id,
    provider.provider_dimension_id,
    facility.facility_dimension_id,
    payer.payer_dimension_id,
    plan.plan_dimension_id,
    diagnosis.diagnosis_dimension_id as primary_diagnosis_dimension_id
  from claims as claim
  left join {{ ref('dim_patient') }} as patient
    on claim.candidate_publication_id = patient.candidate_publication_id
    and claim.candidate_selection_fingerprint = patient.candidate_selection_fingerprint
    and claim.eligibility_source_system = patient.source_system
    and claim.patient_id = patient.patient_id
  left join {{ ref('dim_provider') }} as provider
    on claim.candidate_publication_id = provider.candidate_publication_id
    and claim.candidate_selection_fingerprint = provider.candidate_selection_fingerprint
    and claim.provider_id = provider.provider_id
    and claim.service_from_date >= provider.valid_from
    and (provider.valid_to is null or claim.service_from_date < provider.valid_to)
  left join {{ ref('dim_facility') }} as facility
    on claim.candidate_publication_id = facility.candidate_publication_id
    and claim.candidate_selection_fingerprint = facility.candidate_selection_fingerprint
    and claim.facility_id = facility.facility_id
    and claim.service_from_date >= facility.valid_from
    and (facility.valid_to is null or claim.service_from_date < facility.valid_to)
  left join {{ ref('dim_payer') }} as payer
    on claim.candidate_publication_id = payer.candidate_publication_id
    and claim.candidate_selection_fingerprint = payer.candidate_selection_fingerprint
    and claim.payer_id = payer.payer_id
    and claim.service_from_date >= payer.valid_from
    and (payer.valid_to is null or claim.service_from_date < payer.valid_to)
  left join {{ ref('dim_plan') }} as plan
    on claim.candidate_publication_id = plan.candidate_publication_id
    and claim.candidate_selection_fingerprint = plan.candidate_selection_fingerprint
    and claim.plan_id = plan.plan_id
    and claim.service_from_date >= plan.valid_from
    and (plan.valid_to is null or claim.service_from_date < plan.valid_to)
  left join {{ ref('dim_diagnosis') }} as diagnosis
    on claim.candidate_publication_id = diagnosis.candidate_publication_id
    and claim.candidate_selection_fingerprint = diagnosis.candidate_selection_fingerprint
    and claim.primary_diagnosis_code_system = diagnosis.code_system
    and claim.primary_diagnosis_code = diagnosis.diagnosis_code
    and claim.service_from_date >= diagnosis.valid_from
    and (diagnosis.valid_to is null or claim.service_from_date < diagnosis.valid_to)
)

select
  candidate_publication_id,
  candidate_selection_fingerprint,
  {{
    claimsflow_fact_key(
      'claim',
      [
        ('source_system', 'source_system'),
        ('claim_id', 'claim_id'),
        ('submission_sequence', 'submission_sequence')
      ]
    )
  }} as claim_fact_id,
  case
    when original_claim_source_system is null then cast(null as string)
    else {{
      claimsflow_fact_key(
        'claim',
        [
          ('source_system', 'original_claim_source_system'),
          ('claim_id', 'original_claim_id'),
          ('submission_sequence', 'original_submission_sequence')
        ]
      )
    }}
  end as original_claim_fact_id,
  patient_dimension_id,
  provider_dimension_id,
  facility_dimension_id,
  payer_dimension_id,
  plan_dimension_id,
  primary_diagnosis_dimension_id,
  {{ claimsflow_date_dimension_id('service_from_date') }} as service_from_date_dimension_id,
  {{ claimsflow_date_dimension_id('service_to_date') }} as service_to_date_dimension_id,
  {{ claimsflow_date_dimension_id('submitted_at') }} as submitted_date_dimension_id,
  {{ claimsflow_date_dimension_id('first_response_at') }} as first_response_date_dimension_id,
  {{ claimsflow_date_dimension_id('adjudicated_at') }} as adjudicated_date_dimension_id,
  {{ claimsflow_date_dimension_id('filing_deadline_date') }} as filing_deadline_date_dimension_id,
  source_system,
  claim_id,
  submission_sequence,
  original_claim_source_system,
  original_claim_id,
  original_submission_sequence,
  patient_id,
  eligibility_source_system,
  eligibility_id,
  provider_id,
  facility_id,
  payer_id,
  plan_id,
  claim_type,
  claim_status,
  submission_type,
  service_from_date,
  service_to_date,
  submitted_at,
  first_response_at,
  first_response_disposition,
  adjudicated_at,
  primary_diagnosis_code,
  primary_diagnosis_code_system,
  billed_amount,
  allowed_amount,
  payer_paid_amount,
  patient_paid_amount,
  patient_responsibility_amount,
  adjustment_amount,
  outstanding_balance,
  currency_code,
  clean_claim_flag,
  first_pass_accepted_flag,
  filing_deadline_date,
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
