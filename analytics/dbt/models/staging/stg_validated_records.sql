{{
  config(
    materialized='ephemeral',
    meta={
      'owner': 'ClaimsFlow Data Engineering',
      'publication_scoped': false,
      'purpose': 'Fail-closed allowlist of approved Phase 3 records for one candidate publication'
    }
  )
}}

{% set publication_id = claimsflow_publication_id() %}
{% set selection_fingerprint = claimsflow_publication_selection_fingerprint() %}

with approved_quality_runs as (
  select
    validation_id,
    batch_id,
    report_sha256,
    configuration_sha256,
    evaluation_window_started_at_utc,
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
    record.*,
    {{ claimsflow_normalized_payload_sha256('record') }}
      as computed_normalized_payload_sha256,
    {{ claimsflow_validated_record_evidence_sha256('record') }}
      as computed_record_evidence_sha256
  from {{ source('claimsflow_validated', 'records') }} as record
  where synthetic_only is true
    and disposition in ('accepted', 'accepted_with_warning')
    and {{ claimsflow_validation_filter('validation_id') }}
),

validated_record_sets as (
  select
    validation_id,
    lineage.batch_id as batch_id,
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
),

verified_quality_runs as (
  select quality.*
  from approved_quality_runs as quality
  inner join validated_record_sets as record_set
    on quality.validation_id = record_set.validation_id
    and quality.batch_id = record_set.batch_id
  where quality.validated_record_evidence_algorithm = 'sha256-length-prefixed-utf8-v2'
    and quality.validated_record_set_algorithm
      = 'sha256-sorted-record-evidence-newline-v1'
    and quality.validated_record_count = quality.expected_validated_record_count
    and quality.validated_record_count = record_set.actual_validated_record_count
    and quality.validated_record_set_sha256 = record_set.computed_record_set_sha256
    and record_set.mismatched_record_evidence_count = 0
)

select
  cast('{{ publication_id }}' as string) as candidate_publication_id,
  cast('{{ selection_fingerprint }}' as string) as candidate_selection_fingerprint,
  to_hex(
    sha256(
      to_json_string(
        struct(
          record.lineage.source_identity as source_identity,
          record.lineage.source_system as source_system,
          record.natural_key as natural_key
        )
      )
    )
  ) as validated_record_id,
  record.validation_id,
  record.lineage.batch_id,
  record.lineage.source_identity,
  record.lineage.source_family,
  record.lineage.dataset as source_dataset,
  record.lineage.source_system,
  record.lineage.source_file,
  record.lineage.source_checksum_sha256,
  record.lineage.source_row_number,
  record.lineage.contract_id,
  record.lineage.contract_version,
  record.lineage.ingested_at_utc,
  record.source_record_id,
  record.natural_key,
  record.evaluated_payload_sha256,
  record.computed_normalized_payload_sha256 as normalized_payload_sha256,
  record.computed_record_evidence_sha256 as validated_record_evidence_sha256,
  record.correction_id,
  record.disposition,
  quality.evaluation_window_started_at_utc as validated_at_utc,
  quality.report_sha256 as quality_report_sha256,
  quality.configuration_sha256 as quality_configuration_sha256,
  quality.validated_record_set_sha256,
  record.synthetic_only,
  record.normalized_payload_canonical_json
from validated_record_candidates as record
inner join verified_quality_runs as quality
  on record.validation_id = quality.validation_id
  and record.lineage.batch_id = quality.batch_id
