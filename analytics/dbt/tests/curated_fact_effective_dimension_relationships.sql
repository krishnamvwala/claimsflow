{{ config(tags=['curated_facts', 'phase4b2']) }}

{% set mappings = [
  {'fact': 'fact_claim', 'fact_id': 'claim_fact_id', 'dimension': 'dim_provider', 'dimension_id': 'provider_dimension_id', 'date': 'service_from_date', 'keys': [('provider_id', 'provider_id')]},
  {'fact': 'fact_claim', 'fact_id': 'claim_fact_id', 'dimension': 'dim_facility', 'dimension_id': 'facility_dimension_id', 'date': 'service_from_date', 'keys': [('facility_id', 'facility_id')]},
  {'fact': 'fact_claim', 'fact_id': 'claim_fact_id', 'dimension': 'dim_payer', 'dimension_id': 'payer_dimension_id', 'date': 'service_from_date', 'keys': [('payer_id', 'payer_id')]},
  {'fact': 'fact_claim', 'fact_id': 'claim_fact_id', 'dimension': 'dim_plan', 'dimension_id': 'plan_dimension_id', 'date': 'service_from_date', 'keys': [('plan_id', 'plan_id')]},
  {'fact': 'fact_claim', 'fact_id': 'claim_fact_id', 'dimension': 'dim_diagnosis', 'dimension_id': 'primary_diagnosis_dimension_id', 'date': 'service_from_date', 'keys': [('primary_diagnosis_code_system', 'code_system'), ('primary_diagnosis_code', 'diagnosis_code')]},
  {'fact': 'fact_claim_line', 'fact_id': 'claim_line_fact_id', 'dimension': 'dim_procedure', 'dimension_id': 'procedure_dimension_id', 'date': 'service_from_date', 'keys': [('procedure_code_system', 'code_system'), ('procedure_code', 'procedure_code')]},
  {'fact': 'fact_claim_line', 'fact_id': 'claim_line_fact_id', 'dimension': 'dim_denial_reason', 'dimension_id': 'denial_reason_dimension_id', 'date': 'service_from_date', 'keys': [('denial_reason_code', 'denial_reason_code')]},
  {'fact': 'fact_payment', 'fact_id': 'payment_fact_id', 'dimension': 'dim_payer', 'dimension_id': 'payer_dimension_id', 'date': 'payment_date', 'keys': [('payer_id', 'payer_id')]},
  {'fact': 'fact_denial', 'fact_id': 'denial_fact_id', 'dimension': 'dim_payer', 'dimension_id': 'payer_dimension_id', 'date': 'denial_date', 'keys': [('payer_id', 'payer_id')]},
  {'fact': 'fact_denial', 'fact_id': 'denial_fact_id', 'dimension': 'dim_denial_reason', 'dimension_id': 'denial_reason_dimension_id', 'date': 'denial_date', 'keys': [('denial_reason_code', 'denial_reason_code')]}
] %}

with failures as (
  select
    'fact_claim' as model_name,
    'dim_patient' as dimension_name,
    claim.claim_fact_id as fact_id
  from {{ ref('fact_claim') }} as claim
  left join {{ ref('dim_patient') }} as patient
    on claim.candidate_publication_id = patient.candidate_publication_id
    and claim.candidate_selection_fingerprint = patient.candidate_selection_fingerprint
    and claim.patient_dimension_id = patient.patient_dimension_id
  where patient.patient_dimension_id is null
    or claim.eligibility_source_system is distinct from patient.source_system
    or claim.patient_id is distinct from patient.patient_id

  union all

  {% for mapping in mappings %}
  select
    '{{ mapping['fact'] }}' as model_name,
    '{{ mapping['dimension'] }}' as dimension_name,
    fact.{{ mapping['fact_id'] }} as fact_id
  from {{ ref(mapping['fact']) }} as fact
  left join {{ ref(mapping['dimension']) }} as dimension
    on fact.candidate_publication_id = dimension.candidate_publication_id
    and fact.candidate_selection_fingerprint = dimension.candidate_selection_fingerprint
    and fact.{{ mapping['dimension_id'] }} = dimension.{{ mapping['dimension_id'] }}
  where (
    fact.{{ mapping['keys'][0][0] }} is null
    and fact.{{ mapping['dimension_id'] }} is not null
  )
  or (
    fact.{{ mapping['keys'][0][0] }} is not null
    and (
      fact.{{ mapping['dimension_id'] }} is null
      or dimension.{{ mapping['dimension_id'] }} is null
      {% for key in mapping['keys'] %}
      or fact.{{ key[0] }} is distinct from dimension.{{ key[1] }}
      {% endfor %}
      or fact.{{ mapping['date'] }} < dimension.valid_from
      or (
        dimension.valid_to is not null
        and fact.{{ mapping['date'] }} >= dimension.valid_to
      )
    )
  )
  {% if not loop.last %}union all{% endif %}
  {% endfor %}
)

select * from failures
