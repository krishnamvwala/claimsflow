{{
  claimsflow_stage_validated(
    source_identity='appeals',
    fields=[
      ('appeal_id', 'STRING'),
      ('denial_source_system', 'STRING'),
      ('denial_id', 'STRING'),
      ('claim_source_system', 'STRING'),
      ('claim_id', 'STRING'),
      ('claim_submission_sequence', 'INTEGER'),
      ('appeal_level', 'INTEGER'),
      ('appeal_status', 'STRING'),
      ('created_at', 'TIMESTAMP'),
      ('filed_at', 'TIMESTAMP'),
      ('appeal_deadline_date', 'DATE'),
      ('decision_date', 'DATE'),
      ('outcome', 'STRING'),
      ('requested_amount', 'NUMERIC(18,2)'),
      ('recovered_amount', 'NUMERIC(18,2)'),
      ('currency_code', 'STRING'),
      ('documentation_ready_flag', 'BOOLEAN'),
      ('owner_queue', 'STRING'),
      ('source_updated_at', 'TIMESTAMP')
    ]
  )
}}
