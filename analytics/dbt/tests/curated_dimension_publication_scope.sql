with dimension_rows as (
  {% set models = [
    'dim_date',
    'dim_denial_reason',
    'dim_diagnosis',
    'dim_facility',
    'dim_patient',
    'dim_payer',
    'dim_plan',
    'dim_procedure',
    'dim_provider'
  ] %}
  {% for model_name in models %}
  select
    '{{ model_name }}' as model_name,
    candidate_publication_id,
    candidate_selection_fingerprint,
    synthetic_only
  from {{ ref(model_name) }}
  {% if not loop.last %}union all{% endif %}
  {% endfor %}
)

select *
from dimension_rows
where candidate_publication_id != '{{ claimsflow_publication_id() }}'
  or candidate_selection_fingerprint != '{{ claimsflow_publication_selection_fingerprint() }}'
  or synthetic_only is not true
