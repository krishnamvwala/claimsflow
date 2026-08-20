{{
  claimsflow_stage_validated(
    source_identity='payments',
    fields=[
      ('payment_id', 'STRING'),
      ('remittance_source_system', 'STRING'),
      ('remittance_id', 'STRING'),
      ('claim_source_system', 'STRING'),
      ('claim_id', 'STRING'),
      ('claim_submission_sequence', 'INTEGER'),
      ('claim_line_number', 'INTEGER'),
      ('claim_line_id', 'STRING'),
      ('payer_id', 'STRING'),
      ('transaction_type', 'STRING'),
      ('direction', 'STRING'),
      ('amount', 'NUMERIC(18,2)'),
      ('currency_code', 'STRING'),
      ('payment_date', 'DATE'),
      ('posted_at', 'TIMESTAMP'),
      ('adjustment_reason_code', 'STRING'),
      ('reverses_payment_source_system', 'STRING'),
      ('reverses_payment_id', 'STRING'),
      ('posting_status', 'STRING'),
      ('source_updated_at', 'TIMESTAMP')
    ]
  )
}}
