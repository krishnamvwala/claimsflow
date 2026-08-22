{{ config(tags=['curated_facts', 'phase4b2']) }}

{% set mappings = [
  {'fact': 'fact_claim', 'fact_id': 'claim_fact_id', 'date': 'service_from_date', 'date_id': 'service_from_date_dimension_id'},
  {'fact': 'fact_claim', 'fact_id': 'claim_fact_id', 'date': 'service_to_date', 'date_id': 'service_to_date_dimension_id'},
  {'fact': 'fact_claim', 'fact_id': 'claim_fact_id', 'date': 'submitted_at', 'date_id': 'submitted_date_dimension_id'},
  {'fact': 'fact_claim', 'fact_id': 'claim_fact_id', 'date': 'first_response_at', 'date_id': 'first_response_date_dimension_id'},
  {'fact': 'fact_claim', 'fact_id': 'claim_fact_id', 'date': 'adjudicated_at', 'date_id': 'adjudicated_date_dimension_id'},
  {'fact': 'fact_claim', 'fact_id': 'claim_fact_id', 'date': 'filing_deadline_date', 'date_id': 'filing_deadline_date_dimension_id'},
  {'fact': 'fact_claim_line', 'fact_id': 'claim_line_fact_id', 'date': 'service_from_date', 'date_id': 'service_from_date_dimension_id'},
  {'fact': 'fact_claim_line', 'fact_id': 'claim_line_fact_id', 'date': 'service_to_date', 'date_id': 'service_to_date_dimension_id'},
  {'fact': 'fact_payment', 'fact_id': 'payment_fact_id', 'date': 'payment_date', 'date_id': 'payment_date_dimension_id'},
  {'fact': 'fact_payment', 'fact_id': 'payment_fact_id', 'date': 'posted_at', 'date_id': 'posted_date_dimension_id'},
  {'fact': 'fact_denial', 'fact_id': 'denial_fact_id', 'date': 'denial_date', 'date_id': 'denial_date_dimension_id'},
  {'fact': 'fact_denial', 'fact_id': 'denial_fact_id', 'date': 'received_at', 'date_id': 'received_date_dimension_id'},
  {'fact': 'fact_denial', 'fact_id': 'denial_fact_id', 'date': 'filing_deadline_date', 'date_id': 'filing_deadline_date_dimension_id'},
  {'fact': 'fact_denial', 'fact_id': 'denial_fact_id', 'date': 'appeal_deadline_date', 'date_id': 'appeal_deadline_date_dimension_id'},
  {'fact': 'fact_appeal', 'fact_id': 'appeal_fact_id', 'date': 'created_at', 'date_id': 'created_date_dimension_id'},
  {'fact': 'fact_appeal', 'fact_id': 'appeal_fact_id', 'date': 'filed_at', 'date_id': 'filed_date_dimension_id'},
  {'fact': 'fact_appeal', 'fact_id': 'appeal_fact_id', 'date': 'appeal_deadline_date', 'date_id': 'appeal_deadline_date_dimension_id'},
  {'fact': 'fact_appeal', 'fact_id': 'appeal_fact_id', 'date': 'decision_date', 'date_id': 'decision_date_dimension_id'}
] %}

with failures as (
  {% for mapping in mappings %}
  select
    '{{ mapping['fact'] }}' as model_name,
    '{{ mapping['date_id'] }}' as relationship_name,
    {{ mapping['fact_id'] }} as fact_id
  from {{ ref(mapping['fact']) }}
  where ({{ mapping['date'] }} is null) != ({{ mapping['date_id'] }} is null)
    or {{ mapping['date_id'] }} is distinct from
      {{ claimsflow_date_dimension_id(mapping['date']) }}
  {% if not loop.last %}union all{% endif %}
  {% endfor %}
)

select * from failures
