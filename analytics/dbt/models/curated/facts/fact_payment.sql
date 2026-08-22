{{
  config(
    partition_by={"field": "payment_date", "data_type": "date", "granularity": "month"},
    cluster_by=["claim_fact_id", "payer_dimension_id", "transaction_type"]
  )
}}

with payments as (
  select *
  from {{ ref('stg_payments') }}
),

resolved as (
  select
    payment.*,
    claim.claim_fact_id,
    claim_line.claim_line_fact_id,
    payer.payer_dimension_id,
    remittance.validated_record_id as remittance_source_validated_record_id
  from payments as payment
  left join {{ ref('fact_claim') }} as claim
    on payment.candidate_publication_id = claim.candidate_publication_id
    and payment.candidate_selection_fingerprint = claim.candidate_selection_fingerprint
    and payment.claim_source_system = claim.source_system
    and payment.claim_id = claim.claim_id
    and payment.claim_submission_sequence = claim.submission_sequence
  left join {{ ref('fact_claim_line') }} as claim_line
    on payment.candidate_publication_id = claim_line.candidate_publication_id
    and payment.candidate_selection_fingerprint = claim_line.candidate_selection_fingerprint
    and payment.claim_source_system = claim_line.source_system
    and payment.claim_id = claim_line.claim_id
    and payment.claim_submission_sequence = claim_line.submission_sequence
    and payment.claim_line_number = claim_line.line_number
  left join {{ ref('dim_payer') }} as payer
    on payment.candidate_publication_id = payer.candidate_publication_id
    and payment.candidate_selection_fingerprint = payer.candidate_selection_fingerprint
    and payment.payer_id = payer.payer_id
    and payment.payment_date >= payer.valid_from
    and (payer.valid_to is null or payment.payment_date < payer.valid_to)
  left join {{ ref('stg_remittances') }} as remittance
    on payment.candidate_publication_id = remittance.candidate_publication_id
    and payment.candidate_selection_fingerprint = remittance.candidate_selection_fingerprint
    and payment.remittance_source_system = remittance.source_system
    and payment.remittance_id = remittance.remittance_id
)

select
  candidate_publication_id,
  candidate_selection_fingerprint,
  {{
    claimsflow_fact_key(
      'payment',
      [('source_system', 'source_system'), ('payment_id', 'payment_id')]
    )
  }} as payment_fact_id,
  claim_fact_id,
  claim_line_fact_id,
  case
    when reverses_payment_source_system is null then cast(null as string)
    else {{
      claimsflow_fact_key(
        'payment',
        [
          ('source_system', 'reverses_payment_source_system'),
          ('payment_id', 'reverses_payment_id')
        ]
      )
    }}
  end as reverses_payment_fact_id,
  payer_dimension_id,
  remittance_source_validated_record_id,
  {{ claimsflow_date_dimension_id('payment_date') }} as payment_date_dimension_id,
  {{ claimsflow_date_dimension_id('posted_at') }} as posted_date_dimension_id,
  case when direction = 'credit' then amount else -amount end as signed_amount,
  source_system,
  payment_id,
  remittance_source_system,
  remittance_id,
  claim_source_system,
  claim_id,
  claim_submission_sequence,
  claim_line_number,
  claim_line_id,
  payer_id,
  transaction_type,
  direction,
  amount,
  currency_code,
  payment_date,
  posted_at,
  adjustment_reason_code,
  reverses_payment_source_system,
  reverses_payment_id,
  posting_status,
  source_updated_at,
  validated_record_id as source_validated_record_id,
  validation_id as source_validation_id,
  batch_id as source_batch_id,
  disposition as source_disposition,
  quality_report_sha256,
  quality_configuration_sha256,
  validated_record_set_sha256,
  synthetic_only
from resolved
