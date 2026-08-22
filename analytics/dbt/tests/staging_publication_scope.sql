select
  candidate_publication_id,
  candidate_selection_fingerprint,
  validation_id,
  batch_id,
  source_identity,
  validated_record_id
from {{ ref('stg_validated_records') }}
where candidate_publication_id != '{{ claimsflow_publication_id() }}'
  or candidate_selection_fingerprint != '{{ claimsflow_publication_selection_fingerprint() }}'
  or validation_id not in (
    {% for validation_id in claimsflow_validation_ids() %}
    '{{ validation_id }}'{% if not loop.last %}, {% endif %}
    {% endfor %}
  )
  or synthetic_only is not true
  or disposition not in ('accepted', 'accepted_with_warning')
{{ config(tags=['validated_staging', 'phase4a']) }}
