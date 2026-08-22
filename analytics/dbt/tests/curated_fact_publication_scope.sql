{{ config(tags=['curated_facts', 'phase4b2']) }}

with fact_rows as (
  {% set models = [
    'fact_appeal',
    'fact_claim',
    'fact_claim_line',
    'fact_denial',
    'fact_payment'
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
from fact_rows
where candidate_publication_id != '{{ claimsflow_publication_id() }}'
  or candidate_selection_fingerprint != '{{ claimsflow_publication_selection_fingerprint() }}'
  or synthetic_only is not true
