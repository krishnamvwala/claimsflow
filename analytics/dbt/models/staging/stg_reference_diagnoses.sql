{{
  claimsflow_stage_validated(
    source_identity='reference-data.diagnoses',
    fields=[
      ('diagnosis_code', 'STRING'),
      ('code_system', 'STRING'),
      ('diagnosis_description', 'STRING'),
      ('valid_from', 'DATE'),
      ('valid_to', 'DATE'),
      ('active_flag', 'BOOLEAN')
    ]
  )
}}
