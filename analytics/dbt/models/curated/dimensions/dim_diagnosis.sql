{{
  claimsflow_effective_dimension(
    entity_name='diagnosis',
    source_model='stg_reference_diagnoses',
    business_keys=['code_system', 'diagnosis_code'],
    attributes=['diagnosis_description']
  )
}}
