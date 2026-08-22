with eligibility as (
  select *
  from {{ ref('stg_eligibility') }}
),

patient_rollup as (
  select
    candidate_publication_id,
    candidate_selection_fingerprint,
    source_system,
    patient_id,
    min(verification_at) as first_verified_at,
    max(verification_at) as last_verified_at,
    min(coverage_start_date) as first_coverage_start_date,
    max(coverage_end_date) as last_coverage_end_date,
    count(*) as eligibility_record_count,
    array_agg(distinct validation_id order by validation_id) as source_validation_ids,
    array_agg(distinct batch_id order by batch_id) as source_batch_ids,
    array_agg(
      distinct validated_record_set_sha256 order by validated_record_set_sha256
    ) as validated_record_set_sha256s,
    logical_and(synthetic_only) as synthetic_only
  from eligibility
  group by
    candidate_publication_id,
    candidate_selection_fingerprint,
    source_system,
    patient_id
)

select
  candidate_publication_id,
  candidate_selection_fingerprint,
  {{
    claimsflow_dimension_key(
      'patient-version-v1',
      [('source_system', 'source_system'), ('patient_id', 'patient_id')]
    )
  }} as patient_dimension_id,
  {{
    claimsflow_dimension_key(
      'patient-business-v1',
      [('source_system', 'source_system'), ('patient_id', 'patient_id')]
    )
  }} as patient_business_key,
  source_system,
  patient_id,
  first_verified_at,
  last_verified_at,
  first_coverage_start_date,
  last_coverage_end_date,
  eligibility_record_count,
  source_validation_ids,
  source_batch_ids,
  validated_record_set_sha256s,
  synthetic_only
from patient_rollup
