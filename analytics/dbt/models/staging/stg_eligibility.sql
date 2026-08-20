{{
  claimsflow_stage_validated(
    source_identity='eligibility',
    fields=[
      ('eligibility_id', 'STRING'),
      ('patient_id', 'STRING'),
      ('payer_id', 'STRING'),
      ('plan_id', 'STRING'),
      ('member_reference', 'STRING'),
      ('verification_at', 'TIMESTAMP'),
      ('response_status', 'STRING'),
      ('coverage_status', 'STRING'),
      ('coverage_type', 'STRING'),
      ('coverage_start_date', 'DATE'),
      ('coverage_end_date', 'DATE'),
      ('primary_coverage_flag', 'BOOLEAN'),
      ('deductible_remaining', 'NUMERIC(18,2)'),
      ('out_of_pocket_remaining', 'NUMERIC(18,2)'),
      ('copay_amount', 'NUMERIC(18,2)'),
      ('currency_code', 'STRING'),
      ('source_updated_at', 'TIMESTAMP')
    ]
  )
}}
