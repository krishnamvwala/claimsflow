{{
  claimsflow_effective_dimension(
    entity_name='procedure',
    source_model='stg_reference_procedures',
    business_keys=['code_system', 'procedure_code'],
    attributes=['procedure_description']
  )
}}
