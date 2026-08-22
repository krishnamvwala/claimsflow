{{ config(tags=['curated_facts', 'phase4b2']) }}

with line_rollup as (
  select
    candidate_publication_id,
    candidate_selection_fingerprint,
    claim_fact_id,
    sum(billed_amount) as billed_amount,
    sum(payer_paid_amount) as payer_paid_amount,
    sum(patient_paid_amount) as patient_paid_amount,
    sum(adjustment_amount) as adjustment_amount,
    sum(outstanding_balance) as outstanding_balance
  from {{ ref('fact_claim_line') }}
  group by candidate_publication_id, candidate_selection_fingerprint, claim_fact_id
),

remittance_payment_rollup as (
  select
    candidate_publication_id,
    candidate_selection_fingerprint,
    remittance_source_system,
    remittance_id,
    count(*) as payment_count,
    sum(signed_amount) as signed_amount
  from {{ ref('fact_payment') }}
  where remittance_source_system is not null
    and remittance_id is not null
  group by
    candidate_publication_id,
    candidate_selection_fingerprint,
    remittance_source_system,
    remittance_id
),

appeal_rollup as (
  select
    candidate_publication_id,
    candidate_selection_fingerprint,
    denial_fact_id,
    sum(coalesce(recovered_amount, 0)) as total_recovered_amount
  from {{ ref('fact_appeal') }}
  group by candidate_publication_id, candidate_selection_fingerprint, denial_fact_id
),

failures as (
  select
    'fact_claim' as model_name,
    'claim_financial_equation' as rule_name,
    claim_fact_id as fact_id
  from {{ ref('fact_claim') }}
  where billed_amount != payer_paid_amount + patient_paid_amount + adjustment_amount
      + outstanding_balance
    or patient_paid_amount > patient_responsibility_amount

  union all

  select
    'fact_claim',
    'claim_line_rollup',
    claim.claim_fact_id
  from {{ ref('fact_claim') }} as claim
  left join line_rollup as line
    on claim.candidate_publication_id = line.candidate_publication_id
    and claim.candidate_selection_fingerprint = line.candidate_selection_fingerprint
    and claim.claim_fact_id = line.claim_fact_id
  where line.claim_fact_id is null
    or claim.billed_amount != line.billed_amount
    or claim.payer_paid_amount != line.payer_paid_amount
    or claim.patient_paid_amount != line.patient_paid_amount
    or claim.adjustment_amount != line.adjustment_amount
    or claim.outstanding_balance != line.outstanding_balance

  union all

  select
    'fact_claim_line',
    'line_financial_equation',
    claim_line_fact_id
  from {{ ref('fact_claim_line') }}
  where billed_amount != payer_paid_amount + patient_paid_amount + adjustment_amount
      + outstanding_balance
    or patient_paid_amount > patient_responsibility_amount

  union all

  select
    'fact_payment',
    'payment_sign',
    payment_fact_id
  from {{ ref('fact_payment') }}
  where amount <= 0
    or signed_amount != case when direction = 'credit' then amount else -amount end

  union all

  select
    'fact_payment',
    'remittance_control',
    remittance.validated_record_id
  from {{ ref('stg_remittances') }} as remittance
  left join remittance_payment_rollup as payment
    on remittance.candidate_publication_id = payment.candidate_publication_id
    and remittance.candidate_selection_fingerprint = payment.candidate_selection_fingerprint
    and remittance.source_system = payment.remittance_source_system
    and remittance.remittance_id = payment.remittance_id
  where coalesce(payment.payment_count, 0) != remittance.claim_transaction_count
    or coalesce(payment.signed_amount, cast(0 as numeric)) != case
      when remittance.direction = 'credit' then remittance.total_payment_amount
      else -remittance.total_payment_amount
    end

  union all

  select
    'fact_denial',
    'denial_exposure',
    denial.denial_fact_id
  from {{ ref('fact_denial') }} as denial
  left join {{ ref('fact_claim') }} as claim
    on denial.candidate_publication_id = claim.candidate_publication_id
    and denial.candidate_selection_fingerprint = claim.candidate_selection_fingerprint
    and denial.claim_fact_id = claim.claim_fact_id
  left join {{ ref('fact_claim_line') }} as line
    on denial.candidate_publication_id = line.candidate_publication_id
    and denial.candidate_selection_fingerprint = line.candidate_selection_fingerprint
    and denial.claim_line_fact_id = line.claim_line_fact_id
  where denial.denied_amount <= 0
    or denial.denied_amount > coalesce(line.outstanding_balance, claim.outstanding_balance)

  union all

  select
    'fact_appeal',
    'appeal_amount',
    appeal.appeal_fact_id
  from {{ ref('fact_appeal') }} as appeal
  left join {{ ref('fact_denial') }} as denial
    on appeal.candidate_publication_id = denial.candidate_publication_id
    and appeal.candidate_selection_fingerprint = denial.candidate_selection_fingerprint
    and appeal.denial_fact_id = denial.denial_fact_id
  where appeal.requested_amount <= 0
    or appeal.requested_amount > denial.denied_amount
    or appeal.recovered_amount < 0
    or appeal.recovered_amount > appeal.requested_amount

  union all

  select
    'fact_appeal',
    'denial_total_recovery',
    appeal.denial_fact_id
  from appeal_rollup as appeal
  left join {{ ref('fact_denial') }} as denial
    on appeal.candidate_publication_id = denial.candidate_publication_id
    and appeal.candidate_selection_fingerprint = denial.candidate_selection_fingerprint
    and appeal.denial_fact_id = denial.denial_fact_id
  where denial.denial_fact_id is null
    or appeal.total_recovered_amount > denial.denied_amount
)

select * from failures
