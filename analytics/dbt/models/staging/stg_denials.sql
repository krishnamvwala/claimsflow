{{
  claimsflow_stage_validated(
    source_identity='denials',
    fields=[
      ('denial_id', 'STRING'),
      ('claim_source_system', 'STRING'),
      ('claim_id', 'STRING'),
      ('claim_submission_sequence', 'INTEGER'),
      ('claim_line_number', 'INTEGER'),
      ('claim_line_id', 'STRING'),
      ('payer_id', 'STRING'),
      ('denial_reason_code', 'STRING'),
      ('denial_category', 'STRING'),
      ('denial_date', 'DATE'),
      ('received_at', 'TIMESTAMP'),
      ('denied_amount', 'NUMERIC(18,2)'),
      ('currency_code', 'STRING'),
      ('filing_deadline_date', 'DATE'),
      ('appeal_deadline_date', 'DATE'),
      ('denial_status', 'STRING'),
      ('preventable_flag', 'BOOLEAN'),
      ('documentation_ready_flag', 'BOOLEAN'),
      ('missing_document_codes', 'STRING_LIST'),
      ('source_updated_at', 'TIMESTAMP')
    ]
  )
}}
