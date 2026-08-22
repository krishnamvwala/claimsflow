{{
  claimsflow_effective_dimension(
    entity_name='provider',
    source_model='stg_reference_providers',
    business_keys=['provider_id'],
    attributes=['provider_name', 'specialty_code']
  )
}}
