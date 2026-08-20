{{
  claimsflow_stage_validated(
    source_identity='reference-data.providers',
    fields=[
      ('provider_id', 'STRING'),
      ('provider_name', 'STRING'),
      ('specialty_code', 'STRING'),
      ('valid_from', 'DATE'),
      ('valid_to', 'DATE'),
      ('active_flag', 'BOOLEAN')
    ]
  )
}}
