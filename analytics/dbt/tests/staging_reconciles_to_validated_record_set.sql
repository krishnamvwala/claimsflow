with approved_quality_runs as (
  select
    validation_id,
    batch_id,
    accepted + warned as expected_validated_record_count,
    validated_record_count,
    validated_record_evidence_algorithm,
    validated_record_set_algorithm,
    validated_record_set_sha256
  from {{ source('claimsflow_audit', 'quality_runs') }}
  where synthetic_only is true
    and publication_allowed is true
    and reconciled is true
    and decision = 'approved'
    and {{ claimsflow_validation_filter('validation_id') }}
),

validated_record_candidates as (
  select
    record.validation_id,
    record.lineage.batch_id as batch_id,
    record.record_evidence_sha256,
    record.normalized_payload_sha256,
    {{ claimsflow_normalized_payload_sha256('record') }}
      as computed_normalized_payload_sha256,
    {{ claimsflow_validated_record_evidence_sha256('record') }}
      as computed_record_evidence_sha256
  from {{ source('claimsflow_validated', 'records') }} as record
  where record.synthetic_only is true
    and record.disposition in ('accepted', 'accepted_with_warning')
    and {{ claimsflow_validation_filter('record.validation_id') }}
),

validated_record_sets as (
  select
    validation_id,
    batch_id,
    count(*) as actual_validated_record_count,
    countif(
      record_evidence_sha256 is distinct from computed_record_evidence_sha256
      or normalized_payload_sha256 is distinct from computed_normalized_payload_sha256
    )
      as mismatched_record_evidence_count,
    to_hex(
      sha256(
        coalesce(
          string_agg(
            computed_record_evidence_sha256,
            '\n' order by computed_record_evidence_sha256
          ),
          ''
        )
      )
    ) as computed_record_set_sha256
  from validated_record_candidates
  group by validation_id, batch_id
)

select
  coalesce(quality.validation_id, record_set.validation_id) as validation_id,
  coalesce(quality.batch_id, record_set.batch_id) as batch_id,
  quality.validated_record_set_sha256,
  record_set.computed_record_set_sha256,
  quality.validated_record_count,
  record_set.actual_validated_record_count,
  record_set.mismatched_record_evidence_count
from approved_quality_runs as quality
full outer join validated_record_sets as record_set
  on quality.validation_id = record_set.validation_id
  and quality.batch_id = record_set.batch_id
where quality.validation_id is null
  or record_set.validation_id is null
  or quality.validated_record_evidence_algorithm
    is distinct from 'sha256-length-prefixed-utf8-v2'
  or quality.validated_record_set_algorithm
    is distinct from 'sha256-sorted-record-evidence-newline-v1'
  or quality.validated_record_count is distinct from quality.expected_validated_record_count
  or quality.validated_record_count is distinct from record_set.actual_validated_record_count
  or quality.validated_record_set_sha256
    is distinct from record_set.computed_record_set_sha256
  or record_set.mismatched_record_evidence_count is distinct from 0
{{ config(tags=['validated_staging', 'phase4a']) }}
