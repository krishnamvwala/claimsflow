{{
  claimsflow_stage_validated(
    source_identity='reference-data.denial-reasons',
    fields=[
      ('denial_reason_code', 'STRING'),
      ('denial_category', 'STRING'),
      ('denial_reason_description', 'STRING'),
      ('preventable_default_flag', 'BOOLEAN'),
      ('required_document_codes', 'STRING_LIST'),
      ('historical_resolution_rate', 'NUMERIC(9,4)'),
      ('valid_from', 'DATE'),
      ('valid_to', 'DATE'),
      ('active_flag', 'BOOLEAN')
    ]
  )
}}
