{% macro generate_alias_name(custom_alias_name=none, node=none) -%}
  {%- set base_alias = custom_alias_name | trim if custom_alias_name is not none else node.name -%}
  {%- set metadata = node.config.meta if node is not none and node.config.meta is mapping else {} -%}
  {%- if metadata.get('publication_scoped', false) -%}
    {{ base_alias }}__{{ claimsflow_publication_id() }}__{{ claimsflow_publication_selection_fingerprint() }}__{{ claimsflow_candidate_build_fingerprint() }}
  {%- else -%}
    {{ base_alias }}
  {%- endif -%}
{%- endmacro %}
