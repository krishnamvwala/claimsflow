{% macro claimsflow_json_value(json_expression, field_name, source_type) -%}
  {%- if modules.re.fullmatch('^[a-z][a-z0-9_]*$', field_name) is none -%}
    {{ exceptions.raise_compiler_error("unsafe validated source field: " ~ field_name) }}
  {%- endif -%}
  {%- set json_value_expression = "json_value(" ~ json_expression ~ ", '$." ~ field_name ~ "')" -%}
  {%- if source_type == 'STRING' -%}
    cast({{ json_value_expression }} as string)
  {%- elif source_type == 'STRING_LIST' -%}
    case
      when nullif({{ json_value_expression }}, '') is null then cast([] as array<string>)
      else split({{ json_value_expression }}, '|')
    end
  {%- elif source_type == 'INTEGER' -%}
    safe_cast({{ json_value_expression }} as int64)
  {%- elif source_type.startswith('NUMERIC(') -%}
    safe_cast({{ json_value_expression }} as numeric)
  {%- elif source_type == 'DATE' -%}
    safe_cast({{ json_value_expression }} as date)
  {%- elif source_type == 'TIMESTAMP' -%}
    safe_cast({{ json_value_expression }} as timestamp)
  {%- elif source_type == 'BOOLEAN' -%}
    safe_cast({{ json_value_expression }} as bool)
  {%- else -%}
    {{ exceptions.raise_compiler_error(
      "unsupported validated source type for " ~ field_name ~ ": " ~ source_type
    ) }}
  {%- endif -%}
{%- endmacro %}

{% macro claimsflow_record_evidence_value(field_name, sql_expression) -%}
  concat(
    '{{ field_name }}=',
    case
      when {{ sql_expression }} is null then '-1:'
      else concat(
        cast(byte_length(cast({{ sql_expression }} as string)) as string),
        ':',
        cast({{ sql_expression }} as string)
      )
    end
  )
{%- endmacro %}

{% macro claimsflow_normalized_payload_sha256(record_alias) -%}
  {%- if modules.re.fullmatch('^[a-z][a-z0-9_]*$', record_alias) is none -%}
    {{ exceptions.raise_compiler_error("unsafe normalized payload SQL alias") }}
  {%- endif -%}
  to_hex(sha256(cast({{ record_alias }}.normalized_payload_canonical_json as string)))
{%- endmacro %}

{% macro claimsflow_validated_record_evidence_sha256(record_alias) -%}
  {%- if modules.re.fullmatch('^[a-z][a-z0-9_]*$', record_alias) is none -%}
    {{ exceptions.raise_compiler_error("unsafe validated record SQL alias") }}
  {%- endif -%}
  {%- set normalized_payload_sha256_expression = claimsflow_normalized_payload_sha256(record_alias) -%}
  to_hex(
    sha256(
      concat(
        {{ claimsflow_record_evidence_value('validation_id', record_alias ~ '.validation_id') }}, '|',
        {{ claimsflow_record_evidence_value('batch_id', record_alias ~ '.lineage.batch_id') }}, '|',
        {{ claimsflow_record_evidence_value('source_identity', record_alias ~ '.lineage.source_identity') }}, '|',
        {{ claimsflow_record_evidence_value('source_system', record_alias ~ '.lineage.source_system') }}, '|',
        {{ claimsflow_record_evidence_value('source_record_id', record_alias ~ '.source_record_id') }}, '|',
        {{ claimsflow_record_evidence_value('natural_key', record_alias ~ '.natural_key') }}, '|',
        {{ claimsflow_record_evidence_value('evaluated_payload_sha256', record_alias ~ '.evaluated_payload_sha256') }}, '|',
        {{ claimsflow_record_evidence_value('normalized_payload_sha256', normalized_payload_sha256_expression) }}, '|',
        {{ claimsflow_record_evidence_value('correction_id', record_alias ~ '.correction_id') }}, '|',
        {{ claimsflow_record_evidence_value('disposition', record_alias ~ '.disposition') }}
      )
    )
  )
{%- endmacro %}

{% macro claimsflow_stage_validated(source_identity, fields) -%}
  {%- if modules.re.fullmatch('^[a-z][a-z0-9.-]*$', source_identity) is none -%}
    {{ exceptions.raise_compiler_error("unsafe validated source identity: " ~ source_identity) }}
  {%- endif -%}
  select
    candidate_publication_id,
    candidate_selection_fingerprint,
    validated_record_id,
    validation_id,
    batch_id,
    source_identity,
    source_family,
    source_dataset,
    source_system,
    source_file,
    source_checksum_sha256,
    source_row_number,
    contract_id,
    contract_version,
    ingested_at_utc,
    source_record_id,
    natural_key,
    evaluated_payload_sha256,
    normalized_payload_sha256,
    validated_record_evidence_sha256,
    correction_id,
    disposition,
    validated_at_utc,
    quality_report_sha256,
    quality_configuration_sha256,
    validated_record_set_sha256,
    synthetic_only
    {%- for field in fields %},
    {{ claimsflow_json_value('normalized_payload_canonical_json', field[0], field[1]) }} as {{ adapter.quote(field[0]) }}
    {%- endfor %}
  from {{ ref('stg_validated_records') }}
  where source_identity = '{{ source_identity }}'
{%- endmacro %}
