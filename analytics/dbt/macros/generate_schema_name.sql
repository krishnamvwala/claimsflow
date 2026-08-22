{% macro generate_schema_name(custom_schema_name, node) -%}
  {%- if target.name == 'dev_demo' -%}
    {%- set physical_schemas = {
      'staging': 'claimsflow_curated',
      'intermediate': 'claimsflow_curated',
      'curated': 'claimsflow_curated',
      'semantic': 'claimsflow_semantic',
      'operational': 'claimsflow_operational',
      'audit': 'claimsflow_audit',
      'dbt_test__audit': 'claimsflow_audit'
    } -%}
    {%- if custom_schema_name not in physical_schemas -%}
      {{ exceptions.raise_compiler_error(
        "Unapproved dev/demo dbt schema: " ~ (custom_schema_name or "<none>")
      ) }}
    {%- endif -%}
    {{ physical_schemas[custom_schema_name] }}
  {%- else -%}
    {{ target.schema }}{%- if custom_schema_name is not none -%}_{{ custom_schema_name | trim }}{%- endif -%}
  {%- endif -%}
{%- endmacro %}
