{% macro claimsflow_fact_key(entity_name, fields) -%}
  {%- if modules.re.fullmatch('^[a-z][a-z0-9_]*$', entity_name) is none -%}
    {{ exceptions.raise_compiler_error("unsafe curated fact key entity: " ~ entity_name) }}
  {%- endif -%}
  {{ claimsflow_dimension_key(entity_name ~ '-fact-v1', fields) }}
{%- endmacro %}

{% macro claimsflow_date_dimension_id(date_expression) -%}
  case
    when {{ date_expression }} is null then cast(null as int64)
    else cast(format_date('%Y%m%d', cast({{ date_expression }} as date)) as int64)
  end
{%- endmacro %}
