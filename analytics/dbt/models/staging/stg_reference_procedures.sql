{{
  claimsflow_stage_validated(
    source_identity='reference-data.procedures',
    fields=[
      ('procedure_code', 'STRING'),
      ('code_system', 'STRING'),
      ('procedure_description', 'STRING'),
      ('valid_from', 'DATE'),
      ('valid_to', 'DATE'),
      ('active_flag', 'BOOLEAN')
    ]
  )
}}
