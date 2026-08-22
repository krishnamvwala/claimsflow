{{ config(tags=['curated_facts', 'phase4b2']) }}

with failures as (
  select
    'fact_claim' as model_name,
    'original_claim' as relationship_name,
    claim.claim_fact_id as fact_id
  from {{ ref('fact_claim') }} as claim
  left join {{ ref('fact_claim') }} as original
    on claim.candidate_publication_id = original.candidate_publication_id
    and claim.candidate_selection_fingerprint = original.candidate_selection_fingerprint
    and claim.original_claim_fact_id = original.claim_fact_id
  where (claim.original_claim_source_system is null) != (claim.original_claim_fact_id is null)
    or (
      claim.original_claim_fact_id is not null
      and (
        original.claim_fact_id is null
        or claim.original_claim_source_system is distinct from original.source_system
        or claim.original_claim_id is distinct from original.claim_id
        or claim.original_submission_sequence is distinct from original.submission_sequence
      )
    )

  union all

  select
    'fact_claim_line',
    'claim',
    line.claim_line_fact_id
  from {{ ref('fact_claim_line') }} as line
  left join {{ ref('fact_claim') }} as claim
    on line.candidate_publication_id = claim.candidate_publication_id
    and line.candidate_selection_fingerprint = claim.candidate_selection_fingerprint
    and line.claim_fact_id = claim.claim_fact_id
  where claim.claim_fact_id is null
    or line.source_system is distinct from claim.source_system
    or line.claim_id is distinct from claim.claim_id
    or line.submission_sequence is distinct from claim.submission_sequence

  union all

  select
    'fact_payment',
    'claim',
    payment.payment_fact_id
  from {{ ref('fact_payment') }} as payment
  left join {{ ref('fact_claim') }} as claim
    on payment.candidate_publication_id = claim.candidate_publication_id
    and payment.candidate_selection_fingerprint = claim.candidate_selection_fingerprint
    and payment.claim_fact_id = claim.claim_fact_id
  where claim.claim_fact_id is null
    or payment.claim_source_system is distinct from claim.source_system
    or payment.claim_id is distinct from claim.claim_id
    or payment.claim_submission_sequence is distinct from claim.submission_sequence

  union all

  select
    'fact_payment',
    'claim_line',
    payment.payment_fact_id
  from {{ ref('fact_payment') }} as payment
  left join {{ ref('fact_claim_line') }} as line
    on payment.candidate_publication_id = line.candidate_publication_id
    and payment.candidate_selection_fingerprint = line.candidate_selection_fingerprint
    and payment.claim_line_fact_id = line.claim_line_fact_id
  where (payment.claim_line_number is null) != (payment.claim_line_fact_id is null)
    or (
      payment.claim_line_fact_id is not null
      and (
        line.claim_line_fact_id is null
        or payment.claim_source_system is distinct from line.source_system
        or payment.claim_id is distinct from line.claim_id
        or payment.claim_submission_sequence is distinct from line.submission_sequence
        or payment.claim_line_number is distinct from line.line_number
        or payment.claim_line_id is distinct from line.claim_line_id
      )
    )

  union all

  select
    'fact_payment',
    'remittance',
    payment.payment_fact_id
  from {{ ref('fact_payment') }} as payment
  left join {{ ref('stg_remittances') }} as remittance
    on payment.candidate_publication_id = remittance.candidate_publication_id
    and payment.candidate_selection_fingerprint = remittance.candidate_selection_fingerprint
    and payment.remittance_source_validated_record_id = remittance.validated_record_id
  where (payment.remittance_source_system is null)
      != (payment.remittance_source_validated_record_id is null)
    or (payment.remittance_source_system is null) != (payment.remittance_id is null)
    or (
      payment.remittance_source_validated_record_id is not null
      and (
        remittance.validated_record_id is null
        or payment.remittance_source_system is distinct from remittance.source_system
        or payment.remittance_id is distinct from remittance.remittance_id
      )
    )

  union all

  select
    'fact_payment',
    'reversed_payment',
    payment.payment_fact_id
  from {{ ref('fact_payment') }} as payment
  left join {{ ref('fact_payment') }} as original
    on payment.candidate_publication_id = original.candidate_publication_id
    and payment.candidate_selection_fingerprint = original.candidate_selection_fingerprint
    and payment.reverses_payment_fact_id = original.payment_fact_id
  where (payment.reverses_payment_source_system is null)
      != (payment.reverses_payment_fact_id is null)
    or (
      payment.reverses_payment_fact_id is not null
      and (
        original.payment_fact_id is null
        or payment.reverses_payment_source_system is distinct from original.source_system
        or payment.reverses_payment_id is distinct from original.payment_id
      )
    )

  union all

  select
    'fact_denial',
    'claim',
    denial.denial_fact_id
  from {{ ref('fact_denial') }} as denial
  left join {{ ref('fact_claim') }} as claim
    on denial.candidate_publication_id = claim.candidate_publication_id
    and denial.candidate_selection_fingerprint = claim.candidate_selection_fingerprint
    and denial.claim_fact_id = claim.claim_fact_id
  where claim.claim_fact_id is null
    or denial.claim_source_system is distinct from claim.source_system
    or denial.claim_id is distinct from claim.claim_id
    or denial.claim_submission_sequence is distinct from claim.submission_sequence

  union all

  select
    'fact_denial',
    'claim_line',
    denial.denial_fact_id
  from {{ ref('fact_denial') }} as denial
  left join {{ ref('fact_claim_line') }} as line
    on denial.candidate_publication_id = line.candidate_publication_id
    and denial.candidate_selection_fingerprint = line.candidate_selection_fingerprint
    and denial.claim_line_fact_id = line.claim_line_fact_id
  where (denial.claim_line_number is null) != (denial.claim_line_fact_id is null)
    or (
      denial.claim_line_fact_id is not null
      and (
        line.claim_line_fact_id is null
        or denial.claim_source_system is distinct from line.source_system
        or denial.claim_id is distinct from line.claim_id
        or denial.claim_submission_sequence is distinct from line.submission_sequence
        or denial.claim_line_number is distinct from line.line_number
        or denial.claim_line_id is distinct from line.claim_line_id
      )
    )

  union all

  select
    'fact_appeal',
    'denial',
    appeal.appeal_fact_id
  from {{ ref('fact_appeal') }} as appeal
  left join {{ ref('fact_denial') }} as denial
    on appeal.candidate_publication_id = denial.candidate_publication_id
    and appeal.candidate_selection_fingerprint = denial.candidate_selection_fingerprint
    and appeal.denial_fact_id = denial.denial_fact_id
  where denial.denial_fact_id is null
    or appeal.denial_source_system is distinct from denial.source_system
    or appeal.denial_id is distinct from denial.denial_id
    or appeal.claim_source_system is distinct from denial.claim_source_system
    or appeal.claim_id is distinct from denial.claim_id
    or appeal.claim_submission_sequence is distinct from denial.claim_submission_sequence

  union all

  select
    'fact_appeal',
    'claim',
    appeal.appeal_fact_id
  from {{ ref('fact_appeal') }} as appeal
  left join {{ ref('fact_claim') }} as claim
    on appeal.candidate_publication_id = claim.candidate_publication_id
    and appeal.candidate_selection_fingerprint = claim.candidate_selection_fingerprint
    and appeal.claim_fact_id = claim.claim_fact_id
  where claim.claim_fact_id is null
    or appeal.claim_source_system is distinct from claim.source_system
    or appeal.claim_id is distinct from claim.claim_id
    or appeal.claim_submission_sequence is distinct from claim.submission_sequence
)

select * from failures
