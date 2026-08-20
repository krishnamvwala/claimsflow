{{
  claimsflow_stage_validated(
    source_identity='reference-data.plans',
    fields=[
      ('plan_id', 'STRING'),
      ('payer_id', 'STRING'),
      ('plan_name', 'STRING'),
      ('coverage_type', 'STRING'),
      ('valid_from', 'DATE'),
      ('valid_to', 'DATE'),
      ('active_flag', 'BOOLEAN')
    ]
  )
}}
