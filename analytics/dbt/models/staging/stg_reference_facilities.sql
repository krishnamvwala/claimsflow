{{
  claimsflow_stage_validated(
    source_identity='reference-data.facilities',
    fields=[
      ('facility_id', 'STRING'),
      ('facility_name', 'STRING'),
      ('clinic_number', 'INTEGER'),
      ('region', 'STRING'),
      ('valid_from', 'DATE'),
      ('valid_to', 'DATE'),
      ('active_flag', 'BOOLEAN')
    ]
  )
}}
