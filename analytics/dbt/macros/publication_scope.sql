{% macro claimsflow_publication_id() -%}
  {%- set publication_id = var('claimsflow_publication_id', none) -%}
  {%- if publication_id is not string
        or modules.re.fullmatch('^[a-z][a-z0-9_]{2,47}$', publication_id) is none -%}
    {{ exceptions.raise_compiler_error(
      "claimsflow_publication_id must be a lowercase BigQuery-safe identifier between 3 and 48 characters"
    ) }}
  {%- endif -%}
  {%- if target.name != 'ci' and publication_id == 'ci_phase4a' -%}
    {{ exceptions.raise_compiler_error(
      "non-CI dbt runs must provide a unique claimsflow_publication_id"
    ) }}
  {%- endif -%}
  {{ return(publication_id) }}
{%- endmacro %}

{% macro claimsflow_validation_ids() -%}
  {%- set validation_ids = var('claimsflow_validation_ids', []) -%}
  {%- if validation_ids is string
        or validation_ids is not sequence
        or validation_ids | length == 0 -%}
    {{ exceptions.raise_compiler_error(
      "claimsflow_validation_ids must be a non-empty list of immutable quality validation IDs"
    ) }}
  {%- endif -%}
  {%- set unique_ids = [] -%}
  {%- for validation_id in validation_ids -%}
    {%- if validation_id is not string
          or modules.re.fullmatch('^[A-Za-z0-9][A-Za-z0-9_.-]{2,159}$', validation_id) is none -%}
      {{ exceptions.raise_compiler_error(
        "each claimsflow_validation_ids entry must be a safe immutable identifier"
      ) }}
    {%- endif -%}
    {%- if validation_id not in unique_ids -%}
      {%- do unique_ids.append(validation_id) -%}
    {%- endif -%}
  {%- endfor -%}
  {{ return(unique_ids | sort) }}
{%- endmacro %}

{% macro claimsflow_validation_filter(column_expression) -%}
  {%- set validation_ids = claimsflow_validation_ids() -%}
  {{ column_expression }} in (
    {%- for validation_id in validation_ids -%}
      '{{ validation_id }}'{% if not loop.last %}, {% endif %}
    {%- endfor -%}
  )
{%- endmacro %}

{% macro claimsflow_publication_selection_fingerprint() -%}
  {%- set validation_ids = claimsflow_validation_ids() -%}
  {%- set canonical_selection = 'validated-staging-v1\n' ~ (validation_ids | join('\n')) -%}
  {{ return(local_md5(canonical_selection)) }}
{%- endmacro %}

{% macro claimsflow_code_commit() -%}
  {%- set code_commit = var('claimsflow_code_commit', none) -%}
  {%- if code_commit is not string
        or modules.re.fullmatch('^[0-9a-f]{40}$', code_commit) is none -%}
    {{ exceptions.raise_compiler_error(
      "claimsflow_code_commit must be the exact lowercase 40-character Git commit"
    ) }}
  {%- endif -%}
  {%- if target.name != 'ci'
        and code_commit == '0000000000000000000000000000000000000000' -%}
    {{ exceptions.raise_compiler_error(
      "non-CI dbt runs must provide the exact non-placeholder claimsflow_code_commit"
    ) }}
  {%- endif -%}
  {{ return(code_commit) }}
{%- endmacro %}

{% macro claimsflow_candidate_build_fingerprint() -%}
  {%- set canonical_build = 'candidate-build-v1\n'
      ~ claimsflow_publication_id() ~ '\n'
      ~ claimsflow_publication_selection_fingerprint() ~ '\n'
      ~ claimsflow_code_commit() -%}
  {{ return(local_md5(canonical_build)) }}
{%- endmacro %}
