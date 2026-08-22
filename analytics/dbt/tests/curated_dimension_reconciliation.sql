with expected_counts as (
  {% set reference_models = [
    ('dim_denial_reason', 'stg_reference_denial_reasons'),
    ('dim_diagnosis', 'stg_reference_diagnoses'),
    ('dim_facility', 'stg_reference_facilities'),
    ('dim_payer', 'stg_reference_payers'),
    ('dim_plan', 'stg_reference_plans'),
    ('dim_procedure', 'stg_reference_procedures'),
    ('dim_provider', 'stg_reference_providers')
  ] %}
  {% for model_name, staging_model_name in reference_models %}
  select '{{ model_name }}' as model_name, count(*) as expected_row_count
  from {{ ref(staging_model_name) }}
  union all
  {% endfor %}
  select
    'dim_patient' as model_name,
    count(distinct to_json_string(struct(source_system, patient_id))) as expected_row_count
  from {{ ref('stg_eligibility') }}
),

actual_counts as (
  {% set dimension_models = [
    'dim_denial_reason',
    'dim_diagnosis',
    'dim_facility',
    'dim_patient',
    'dim_payer',
    'dim_plan',
    'dim_procedure',
    'dim_provider'
  ] %}
  {% for model_name in dimension_models %}
  select '{{ model_name }}' as model_name, count(*) as actual_row_count
  from {{ ref(model_name) }}
  {% if not loop.last %}union all{% endif %}
  {% endfor %}
)

select
  coalesce(expected_counts.model_name, actual_counts.model_name) as model_name,
  expected_counts.expected_row_count,
  actual_counts.actual_row_count
from expected_counts
full outer join actual_counts using (model_name)
where expected_counts.expected_row_count is distinct from actual_counts.actual_row_count
{{ config(tags=['curated_dimensions', 'phase4b1']) }}
