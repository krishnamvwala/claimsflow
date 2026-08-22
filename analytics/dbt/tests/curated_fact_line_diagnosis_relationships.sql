{{ config(tags=['curated_facts', 'phase4b2']) }}

with line_failures as (
  select
    line.claim_line_fact_id,
    diagnosis_offset,
    diagnosis_code,
    line.diagnosis_dimension_ids[safe_offset(diagnosis_offset)] as diagnosis_dimension_id,
    diagnosis.diagnosis_dimension_id as resolved_dimension_id
  from {{ ref('fact_claim_line') }} as line
  left join unnest(line.diagnosis_codes) as diagnosis_code with offset as diagnosis_offset
  left join {{ ref('dim_diagnosis') }} as diagnosis
    on line.candidate_publication_id = diagnosis.candidate_publication_id
    and line.candidate_selection_fingerprint = diagnosis.candidate_selection_fingerprint
    and line.diagnosis_dimension_ids[safe_offset(diagnosis_offset)]
      = diagnosis.diagnosis_dimension_id
  where array_length(line.diagnosis_codes) = 0
    or array_length(line.diagnosis_codes) != array_length(line.diagnosis_dimension_ids)
    or diagnosis.diagnosis_dimension_id is null
    or line.diagnosis_code_system is distinct from diagnosis.code_system
    or diagnosis_code is distinct from diagnosis.diagnosis_code
    or line.service_from_date < diagnosis.valid_from
    or (
      diagnosis.valid_to is not null
      and line.service_from_date >= diagnosis.valid_to
    )
)

select * from line_failures
