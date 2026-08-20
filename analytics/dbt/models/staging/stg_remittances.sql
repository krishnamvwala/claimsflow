{{
  claimsflow_stage_validated(
    source_identity='remittances',
    fields=[
      ('remittance_id', 'STRING'),
      ('reverses_remittance_source_system', 'STRING'),
      ('reverses_remittance_id', 'STRING'),
      ('payer_id', 'STRING'),
      ('source_control_number', 'STRING'),
      ('payment_trace_number', 'STRING'),
      ('payment_method', 'STRING'),
      ('direction', 'STRING'),
      ('remittance_date', 'DATE'),
      ('received_at', 'TIMESTAMP'),
      ('total_payment_amount', 'NUMERIC(18,2)'),
      ('claim_transaction_count', 'INTEGER'),
      ('currency_code', 'STRING'),
      ('remittance_status', 'STRING'),
      ('source_updated_at', 'TIMESTAMP')
    ]
  )
}}
