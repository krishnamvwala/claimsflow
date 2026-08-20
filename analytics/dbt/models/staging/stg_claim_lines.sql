{{
  claimsflow_stage_validated(
    source_identity='claim-lines',
    fields=[
      ('claim_id', 'STRING'),
      ('submission_sequence', 'INTEGER'),
      ('line_number', 'INTEGER'),
      ('claim_line_id', 'STRING'),
      ('service_from_date', 'DATE'),
      ('service_to_date', 'DATE'),
      ('procedure_code', 'STRING'),
      ('procedure_code_system', 'STRING'),
      ('procedure_modifiers', 'STRING_LIST'),
      ('diagnosis_codes', 'STRING_LIST'),
      ('diagnosis_code_system', 'STRING'),
      ('place_of_service_code', 'STRING'),
      ('revenue_code', 'STRING'),
      ('units', 'NUMERIC(9,4)'),
      ('line_status', 'STRING'),
      ('denial_reason_code', 'STRING'),
      ('billed_amount', 'NUMERIC(18,2)'),
      ('allowed_amount', 'NUMERIC(18,2)'),
      ('payer_paid_amount', 'NUMERIC(18,2)'),
      ('patient_paid_amount', 'NUMERIC(18,2)'),
      ('patient_responsibility_amount', 'NUMERIC(18,2)'),
      ('adjustment_amount', 'NUMERIC(18,2)'),
      ('outstanding_balance', 'NUMERIC(18,2)'),
      ('currency_code', 'STRING'),
      ('source_updated_at', 'TIMESTAMP')
    ]
  )
}}
