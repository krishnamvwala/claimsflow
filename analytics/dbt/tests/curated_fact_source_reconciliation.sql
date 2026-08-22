{{ config(tags=['curated_facts', 'phase4b2']) }}

{% set mappings = [
  {'fact': 'fact_appeal', 'source': 'stg_appeals', 'amounts': ['requested_amount', 'recovered_amount']},
  {'fact': 'fact_claim', 'source': 'stg_claims', 'amounts': ['billed_amount', 'allowed_amount', 'payer_paid_amount', 'patient_paid_amount', 'patient_responsibility_amount', 'adjustment_amount', 'outstanding_balance']},
  {'fact': 'fact_claim_line', 'source': 'stg_claim_lines', 'amounts': ['billed_amount', 'allowed_amount', 'payer_paid_amount', 'patient_paid_amount', 'patient_responsibility_amount', 'adjustment_amount', 'outstanding_balance']},
  {'fact': 'fact_denial', 'source': 'stg_denials', 'amounts': ['denied_amount']},
  {'fact': 'fact_payment', 'source': 'stg_payments', 'amounts': ['amount']}
] %}

with source_rollup as (
  {% for mapping in mappings %}
  select
    '{{ mapping['fact'] }}' as model_name,
    candidate_publication_id,
    candidate_selection_fingerprint,
    count(*) as row_count,
    to_json_string(struct(
      {% for amount in mapping['amounts'] %}
      sum({{ amount }}) as {{ amount }}{% if not loop.last %},{% endif %}
      {% endfor %}
    )) as financial_control
  from {{ ref(mapping['source']) }}
  group by candidate_publication_id, candidate_selection_fingerprint
  {% if not loop.last %}union all{% endif %}
  {% endfor %}
),

fact_rollup as (
  {% for mapping in mappings %}
  select
    '{{ mapping['fact'] }}' as model_name,
    candidate_publication_id,
    candidate_selection_fingerprint,
    count(*) as row_count,
    to_json_string(struct(
      {% for amount in mapping['amounts'] %}
      sum({{ amount }}) as {{ amount }}{% if not loop.last %},{% endif %}
      {% endfor %}
    )) as financial_control
  from {{ ref(mapping['fact']) }}
  group by candidate_publication_id, candidate_selection_fingerprint
  {% if not loop.last %}union all{% endif %}
  {% endfor %}
)

select
  coalesce(source.model_name, fact.model_name) as model_name,
  coalesce(source.candidate_publication_id, fact.candidate_publication_id) as candidate_publication_id,
  coalesce(source.candidate_selection_fingerprint, fact.candidate_selection_fingerprint)
    as candidate_selection_fingerprint,
  source.row_count as source_row_count,
  fact.row_count as fact_row_count,
  source.financial_control as source_financial_control,
  fact.financial_control as fact_financial_control
from source_rollup as source
full outer join fact_rollup as fact
  on source.model_name = fact.model_name
  and source.candidate_publication_id = fact.candidate_publication_id
  and source.candidate_selection_fingerprint = fact.candidate_selection_fingerprint
where source.row_count is distinct from fact.row_count
  or source.financial_control is distinct from fact.financial_control
