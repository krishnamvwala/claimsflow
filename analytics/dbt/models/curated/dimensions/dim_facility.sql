{{
  claimsflow_effective_dimension(
    entity_name='facility',
    source_model='stg_reference_facilities',
    business_keys=['facility_id'],
    attributes=['facility_name', 'clinic_number', 'region']
  )
}}
