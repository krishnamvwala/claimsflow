with typed_records as (
  {% set models = [
    'stg_appeals',
    'stg_claim_lines',
    'stg_claims',
    'stg_denials',
    'stg_eligibility',
    'stg_payments',
    'stg_reference_denial_reasons',
    'stg_reference_diagnoses',
    'stg_reference_facilities',
    'stg_reference_payers',
    'stg_reference_plans',
    'stg_reference_procedures',
    'stg_reference_providers',
    'stg_remittances'
  ] %}
  {% for model_name in models %}
  select
    candidate_publication_id,
    candidate_selection_fingerprint,
    validated_record_id,
    validation_id,
    batch_id,
    source_identity,
    source_system,
    natural_key,
    evaluated_payload_sha256,
    normalized_payload_sha256,
    validated_record_evidence_sha256,
    validated_record_set_sha256
  from {{ ref(model_name) }}
  {% if not loop.last %}union all{% endif %}
  {% endfor %}
),

validated_records as (
  select
    candidate_publication_id,
    candidate_selection_fingerprint,
    validated_record_id,
    validation_id,
    batch_id,
    source_identity,
    source_system,
    natural_key,
    evaluated_payload_sha256,
    normalized_payload_sha256,
    validated_record_evidence_sha256,
    validated_record_set_sha256
  from {{ ref('stg_validated_records') }}
),

missing_from_typed_models as (
  select * from validated_records
  except distinct
  select * from typed_records
),

unexpected_in_typed_models as (
  select * from typed_records
  except distinct
  select * from validated_records
)

select 'missing_from_typed_models' as reconciliation_failure, *
from missing_from_typed_models
union all
select 'unexpected_in_typed_models' as reconciliation_failure, *
from unexpected_in_typed_models
{{ config(tags=['validated_staging', 'phase4a']) }}
