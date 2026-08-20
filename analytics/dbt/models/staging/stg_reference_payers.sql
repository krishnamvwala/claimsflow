{{
  claimsflow_stage_validated(
    source_identity='reference-data.payers',
    fields=[
      ('payer_id', 'STRING'),
      ('payer_name', 'STRING'),
      ('payer_type', 'STRING'),
      ('timely_filing_days', 'INTEGER'),
      ('appeal_window_days', 'INTEGER'),
      ('expected_response_days', 'INTEGER'),
      ('historical_resolution_rate', 'NUMERIC(9,4)'),
      ('valid_from', 'DATE'),
      ('valid_to', 'DATE'),
      ('active_flag', 'BOOLEAN')
    ]
  )
}}
