{% macro claimsflow_dimension_key(key_namespace, fields) -%}
  {%- if modules.re.fullmatch('^[a-z][a-z0-9_-]*$', key_namespace) is none -%}
    {{ exceptions.raise_compiler_error("unsafe curated dimension key namespace: " ~ key_namespace) }}
  {%- endif -%}
  {%- for field in fields -%}
    {%- if field | length != 2
          or modules.re.fullmatch('^[a-z][a-z0-9_]*$', field[0]) is none
          or modules.re.fullmatch('^[a-z][a-z0-9_.]*$', field[1]) is none -%}
      {{ exceptions.raise_compiler_error("unsafe curated dimension key field") }}
    {%- endif -%}
  {%- endfor -%}
  to_hex(
    sha256(
      to_json_string(
        struct(
          cast('{{ key_namespace }}' as string) as key_namespace
          {%- for field in fields %},
          {{ field[1] }} as {{ field[0] }}
          {%- endfor %}
        )
      )
    )
  )
{%- endmacro %}

{% macro claimsflow_effective_dimension(entity_name, source_model, business_keys, attributes) -%}
  {%- if modules.re.fullmatch('^[a-z][a-z0-9_]*$', entity_name) is none
        or modules.re.fullmatch('^stg_reference_[a-z][a-z0-9_]*$', source_model) is none -%}
    {{ exceptions.raise_compiler_error("unsafe effective-dimension configuration") }}
  {%- endif -%}
  {%- for column_name in business_keys + attributes -%}
    {%- if modules.re.fullmatch('^[a-z][a-z0-9_]*$', column_name) is none -%}
      {{ exceptions.raise_compiler_error("unsafe effective-dimension column: " ~ column_name) }}
    {%- endif -%}
  {%- endfor -%}
  {%- set version_key_fields = [('source_system', 'source_system')] -%}
  {%- set business_key_fields = [('source_system', 'source_system')] -%}
  {%- for column_name in business_keys -%}
    {%- do version_key_fields.append((column_name, column_name)) -%}
    {%- do business_key_fields.append((column_name, column_name)) -%}
  {%- endfor -%}
  {%- do version_key_fields.append(('valid_from', 'valid_from')) -%}

  select
    candidate_publication_id,
    candidate_selection_fingerprint,
    {{ claimsflow_dimension_key(entity_name ~ '-version-v1', version_key_fields) }}
      as {{ entity_name }}_dimension_id,
    {{ claimsflow_dimension_key(entity_name ~ '-business-v1', business_key_fields) }}
      as {{ entity_name }}_business_key,
    source_system,
    {%- for column_name in business_keys %}
    {{ column_name }},
    {%- endfor %}
    {%- for column_name in attributes %}
    {{ column_name }},
    {%- endfor %}
    valid_from,
    valid_to,
    active_flag as source_active_flag,
    valid_to is null as is_current,
    validated_record_id as source_validated_record_id,
    validation_id as source_validation_id,
    batch_id as source_batch_id,
    quality_report_sha256,
    quality_configuration_sha256,
    validated_record_set_sha256,
    synthetic_only
  from {{ ref(source_model) }}
{%- endmacro %}

{% macro claimsflow_candidate_dates() %}
  {% set date_sources = [
    ('stg_appeals', 'created_at'),
    ('stg_appeals', 'filed_at'),
    ('stg_appeals', 'appeal_deadline_date'),
    ('stg_appeals', 'decision_date'),
    ('stg_appeals', 'source_updated_at'),
    ('stg_claim_lines', 'service_from_date'),
    ('stg_claim_lines', 'service_to_date'),
    ('stg_claim_lines', 'source_updated_at'),
    ('stg_claims', 'service_from_date'),
    ('stg_claims', 'service_to_date'),
    ('stg_claims', 'submitted_at'),
    ('stg_claims', 'first_response_at'),
    ('stg_claims', 'adjudicated_at'),
    ('stg_claims', 'filing_deadline_date'),
    ('stg_claims', 'source_updated_at'),
    ('stg_denials', 'denial_date'),
    ('stg_denials', 'received_at'),
    ('stg_denials', 'filing_deadline_date'),
    ('stg_denials', 'appeal_deadline_date'),
    ('stg_denials', 'source_updated_at'),
    ('stg_eligibility', 'verification_at'),
    ('stg_eligibility', 'coverage_start_date'),
    ('stg_eligibility', 'coverage_end_date'),
    ('stg_eligibility', 'source_updated_at'),
    ('stg_payments', 'payment_date'),
    ('stg_payments', 'posted_at'),
    ('stg_payments', 'source_updated_at'),
    ('stg_remittances', 'remittance_date'),
    ('stg_remittances', 'received_at'),
    ('stg_remittances', 'source_updated_at'),
    ('stg_reference_denial_reasons', 'valid_from'),
    ('stg_reference_denial_reasons', 'valid_to'),
    ('stg_reference_diagnoses', 'valid_from'),
    ('stg_reference_diagnoses', 'valid_to'),
    ('stg_reference_facilities', 'valid_from'),
    ('stg_reference_facilities', 'valid_to'),
    ('stg_reference_payers', 'valid_from'),
    ('stg_reference_payers', 'valid_to'),
    ('stg_reference_plans', 'valid_from'),
    ('stg_reference_plans', 'valid_to'),
    ('stg_reference_procedures', 'valid_from'),
    ('stg_reference_procedures', 'valid_to'),
    ('stg_reference_providers', 'valid_from'),
    ('stg_reference_providers', 'valid_to')
  ] %}
  {% for source in date_sources %}
  select
    candidate_publication_id,
    candidate_selection_fingerprint,
    cast({{ source[1] }} as date) as candidate_date
  from {{ ref(source[0]) }}
    {% if not loop.last %}
  union all
    {% endif %}
  {% endfor %}
{% endmacro %}

{% macro claimsflow_max_date_spine_days() -%}
  {{ return(36600) }}
{%- endmacro %}
