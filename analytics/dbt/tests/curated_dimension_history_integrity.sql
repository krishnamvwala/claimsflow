with history_failures as (
  {% set dimensions = [
    ('dim_denial_reason', 'denial_reason'),
    ('dim_diagnosis', 'diagnosis'),
    ('dim_facility', 'facility'),
    ('dim_payer', 'payer'),
    ('dim_plan', 'plan'),
    ('dim_procedure', 'procedure'),
    ('dim_provider', 'provider')
  ] %}
  {% for model_name, entity_name in dimensions %}
  select
    '{{ model_name }}' as model_name,
    'invalid_effective_interval_or_current_flag' as failure_type,
    {{ entity_name }}_dimension_id as dimension_id
  from {{ ref(model_name) }}
  where valid_to <= valid_from
    or is_current != (valid_to is null)
    or source_active_flag != (valid_to is null)
  union all
  select
    '{{ model_name }}' as model_name,
    'overlapping_history_versions' as failure_type,
    earlier.{{ entity_name }}_dimension_id as dimension_id
  from {{ ref(model_name) }} as earlier
  inner join {{ ref(model_name) }} as later
    on earlier.candidate_publication_id = later.candidate_publication_id
    and earlier.candidate_selection_fingerprint = later.candidate_selection_fingerprint
    and earlier.{{ entity_name }}_business_key = later.{{ entity_name }}_business_key
    and earlier.{{ entity_name }}_dimension_id < later.{{ entity_name }}_dimension_id
    and earlier.valid_from < coalesce(later.valid_to, date '9999-12-31')
    and later.valid_from < coalesce(earlier.valid_to, date '9999-12-31')
  {% if not loop.last %}union all{% endif %}
  {% endfor %}
)

select * from history_failures
{{ config(tags=['curated_dimensions', 'phase4b1']) }}
