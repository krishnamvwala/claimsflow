#!/usr/bin/env ruby
# frozen_string_literal: true

require "json"
require "yaml"

ROOT = File.expand_path("..", __dir__)

REQUIRED_FILES = %w[
  .dockerignore
  .env.example
  .gitignore
  .python-version
  Makefile
  README.md
  analytics/dbt/README.md
  analytics/dbt/dbt_project.yml
  analytics/dbt/macros/generate_alias_name.sql
  analytics/dbt/macros/generate_schema_name.sql
  analytics/dbt/macros/publication_scope.sql
  analytics/dbt/macros/stage_validated.sql
  analytics/dbt/macros/curated_dimensions.sql
  analytics/dbt/macros/curated_facts.sql
  analytics/dbt/models/staging/_sources.yml
  analytics/dbt/models/staging/_staging.yml
  analytics/dbt/models/staging/README.md
  analytics/dbt/models/staging/stg_validated_records.sql
  analytics/dbt/models/intermediate/README.md
  analytics/dbt/models/curated/README.md
  analytics/dbt/models/curated/dimensions/_dimensions.yml
  analytics/dbt/models/curated/dimensions/dim_date.sql
  analytics/dbt/models/curated/dimensions/dim_denial_reason.sql
  analytics/dbt/models/curated/dimensions/dim_diagnosis.sql
  analytics/dbt/models/curated/dimensions/dim_facility.sql
  analytics/dbt/models/curated/dimensions/dim_patient.sql
  analytics/dbt/models/curated/dimensions/dim_payer.sql
  analytics/dbt/models/curated/dimensions/dim_plan.sql
  analytics/dbt/models/curated/dimensions/dim_procedure.sql
  analytics/dbt/models/curated/dimensions/dim_provider.sql
  analytics/dbt/models/curated/facts/_facts.yml
  analytics/dbt/models/curated/facts/fact_appeal.sql
  analytics/dbt/models/curated/facts/fact_claim.sql
  analytics/dbt/models/curated/facts/fact_claim_line.sql
  analytics/dbt/models/curated/facts/fact_denial.sql
  analytics/dbt/models/curated/facts/fact_payment.sql
  analytics/dbt/models/publication/_publication.yml
  analytics/dbt/models/publication/active_publication_membership.sql
  analytics/dbt/models/semantic/README.md
  analytics/dbt/models/operational/README.md
  analytics/dbt/tests/staging_publication_scope.sql
  analytics/dbt/tests/staging_reconciles_to_quality_counts.sql
  analytics/dbt/tests/staging_reconciles_to_typed_models.sql
  analytics/dbt/tests/staging_reconciles_to_validated_record_set.sql
  analytics/dbt/tests/staging_requires_every_validation.sql
  analytics/dbt/tests/curated_date_coverage.sql
  analytics/dbt/tests/curated_date_span_bound.sql
  analytics/dbt/tests/curated_dimension_history_integrity.sql
  analytics/dbt/tests/curated_dimension_publication_scope.sql
  analytics/dbt/tests/curated_dimension_reconciliation.sql
  analytics/dbt/tests/curated_plan_payer_effective_relationship.sql
  analytics/dbt/tests/curated_fact_date_keys.sql
  analytics/dbt/tests/curated_fact_effective_dimension_relationships.sql
  analytics/dbt/tests/curated_fact_financial_integrity.sql
  analytics/dbt/tests/curated_fact_line_diagnosis_relationships.sql
  analytics/dbt/tests/curated_fact_parent_relationships.sql
  analytics/dbt/tests/curated_fact_publication_scope.sql
  analytics/dbt/tests/curated_fact_source_reconciliation.sql
  analytics/dbt/tests/publication_active_membership_integrity.sql
  compose.yaml
  config/dbt/profiles.yml
  config/data-quality-policy.yml
  config/release-manifest.example.json
  config/release-manifest.schema.json
  config/publication-manifest.example.json
  config/publication-manifest.schema.json
  docs/development/README.md
  docs/development/data-quality-quarantine.md
  docs/development/dbt-validated-staging.md
  docs/development/dbt-curated-dimensions.md
  docs/development/dbt-curated-facts.md
  docs/development/safe-publication.md
  docs/development/component-inventory.md
  infra/terraform/environments/dev-demo/README.md
  infra/terraform/environments/dev-demo/.terraform.lock.hcl
  infra/terraform/environments/dev-demo/main.tf
  infra/terraform/environments/dev-demo/terraform.tfvars.example
  infra/terraform/environments/dev-demo/versions.tf
  infra/terraform/environments/local/README.md
  infra/terraform/environments/local/main.tf
  infra/terraform/environments/local/versions.tf
  infra/terraform/modules/foundation/README.md
  infra/terraform/modules/foundation/main.tf
  infra/terraform/modules/foundation/variables.tf
  infra/terraform/modules/foundation/versions.tf
  orchestration/airflow/Dockerfile
  orchestration/airflow/README.md
  orchestration/airflow/dags/claimsflow_batch.py
  orchestration/airflow/policy/validate_dag.py
  pyproject.toml
  scripts/render_dbt_staging_properties.py
  scripts/render_dbt_curated_dimension_properties.py
  scripts/render_dbt_curated_fact_properties.py
  src/claimsflow/cli.py
  src/claimsflow/config.py
  src/claimsflow/adapters/bigquery_publication.py
  src/claimsflow/adapters/in_memory_publication.py
  src/claimsflow/domain/publication.py
  src/claimsflow/ports/publication.py
  src/claimsflow/publication/__init__.py
  src/claimsflow/publication/service.py
  src/claimsflow/domain/quality.py
  src/claimsflow/logging_config.py
  src/claimsflow/quality/__init__.py
  src/claimsflow/quality/catalog.py
  src/claimsflow/quality/engine.py
  src/claimsflow/quality/service.py
  tests/unit/test_cli.py
  tests/unit/test_config.py
  tests/unit/test_dbt_staging_contract.py
  tests/unit/test_dbt_curated_dimension_contract.py
  tests/unit/test_dbt_curated_fact_contract.py
  tests/unit/test_dbt_publication_contract.py
  tests/unit/test_bigquery_publication_adapter.py
  tests/unit/test_publication_manifest.py
  tests/unit/test_publication_service.py
  tests/integration/test_bigquery_publication_concurrency.py
  tests/unit/test_logging_config.py
  tests/unit/test_quality_engine.py
  tests/unit/test_quality_service.py
  tests/unit/test_release_manifest.py
  uv.lock
  .github/workflows/project-foundation.yml
].freeze

DBT_LAYERS = %w[staging intermediate curated semantic operational].freeze
STAGING_MODELS = {
  "appeals" => "stg_appeals",
  "claim-lines" => "stg_claim_lines",
  "claims" => "stg_claims",
  "denials" => "stg_denials",
  "eligibility" => "stg_eligibility",
  "payments" => "stg_payments",
  "reference-data.denial-reasons" => "stg_reference_denial_reasons",
  "reference-data.diagnoses" => "stg_reference_diagnoses",
  "reference-data.facilities" => "stg_reference_facilities",
  "reference-data.payers" => "stg_reference_payers",
  "reference-data.plans" => "stg_reference_plans",
  "reference-data.procedures" => "stg_reference_procedures",
  "reference-data.providers" => "stg_reference_providers",
  "remittances" => "stg_remittances"
}.freeze
CURATED_DIMENSION_MODELS = %w[
  dim_date
  dim_denial_reason
  dim_diagnosis
  dim_facility
  dim_patient
  dim_payer
  dim_plan
  dim_procedure
  dim_provider
].freeze
CURATED_FACT_MODELS = %w[
  fact_appeal
  fact_claim
  fact_claim_line
  fact_denial
  fact_payment
].freeze
PUBLICATION_MODELS = %w[
  active_publication_membership
].freeze
DATASET_LAYERS = %w[raw validated quarantine curated semantic operational audit].freeze
WORKLOAD_ACCOUNTS = %w[ingestion transformation orchestration bi auditor deployment].freeze
DAG_TASKS = %w[
  register_delivery
  verify_landing_object
  load_raw
  validate_batch
  build_candidate
  reconcile
  evaluate_publication_gates
  advance_publication
  refresh_bi
  evaluate_alerts
].freeze
AIRFLOW_IMAGE = "apache/airflow:3.3.1-python3.12@sha256:b01a795dfbd113bbbfdf3ee169b8f27e9a0090ccef105f1a452b3594a11ed316"
ACTION_PINS = {
  "actions/checkout" => "3d3c42e5aac5ba805825da76410c181273ba90b1",
  "ruby/setup-ruby" => "95ef2b042f9d7a56d8268cba8559e2842e2ad01b",
  "astral-sh/setup-uv" => "ae62891fec2bb8e7d6c99fc78c9fec3a63790f8d",
  "hashicorp/setup-terraform" => "dfe3c3f87815947d99a8997f908cb6525fc44e9e",
  "gitleaks/gitleaks-action" => "e0c47f4f8be36e29cdc102c57e68cb5cbf0e8d1e",
  "actions/dependency-review-action" => "a1d282b36b6f3519aa1f3fc636f609c47dddb294"
}.freeze
GENERATED_PATH_COMPONENTS = %w[
  .mypy_cache
  .pytest_cache
  .ruff_cache
  .terraform
  .venv
  __pycache__
  db
  dbt_packages
  logs
  target
].freeze
CI_PATHS = %w[
  .env.example
  .python-version
  README.md
  analytics/dbt/**
  compose.yaml
  config/**
  docs/development/**
  infra/terraform/**
  orchestration/airflow/**
  pyproject.toml
  scripts/render_dbt_staging_properties.py
  scripts/render_dbt_curated_dimension_properties.py
  scripts/render_dbt_curated_fact_properties.py
  src/**
  tests/**
  uv.lock
].freeze

def relative(path)
  path.delete_prefix("#{ROOT}/")
end

def read_file(path, errors)
  absolute = File.join(ROOT, path)
  unless File.file?(absolute)
    errors << "Missing required scaffold file: #{path}"
    return ""
  end
  File.read(absolute)
end

def require_text(content, expected, context, errors)
  errors << "#{context} must contain #{expected.inspect}" unless content.include?(expected)
end

def reject_text(content, prohibited, context, errors)
  errors << "#{context} must not contain #{prohibited.inspect}" if content.downcase.include?(prohibited.downcase)
end

errors = []

REQUIRED_FILES.each do |path|
  errors << "Missing required scaffold file: #{path}" unless File.file?(File.join(ROOT, path))
end

python_version = read_file(".python-version", errors).strip
errors << ".python-version must pin Python 3.12" unless python_version == "3.12"

pyproject = read_file("pyproject.toml", errors)
[
  'requires-python = ">=3.12,<3.13"',
  '"mypy==2.3.0"',
  '"jsonschema[format]==4.26.0"',
  '"types-jsonschema==4.26.0.20260518"',
  '"pytest==9.1.1"',
  '"ruff==0.16.3"',
  '"google-cloud-bigquery==3.43.0"',
  '"google-cloud-storage==3.1.1"',
  '"dbt-bigquery==1.12.0"'
].each { |text| require_text(pyproject, text, "pyproject.toml", errors) }

dependency_lines = pyproject.lines.select { |line| line.strip.match?(/\A"[a-z0-9][^\"]+",\z/i) }
dependency_lines.each do |line|
  next unless line.include?(">=") || line.include?("~=") || line.include?("*")

  errors << "pyproject.toml dependency entries must use exact pins: #{line.strip}"
end

environment = read_file(".env.example", errors)
require_text(environment, "CLAIMSFLOW_SYNTHETIC_ONLY=true", ".env.example", errors)
require_text(environment, "CLAIMSFLOW_GCP_PROJECT=\n", ".env.example", errors)
require_text(environment, "CLAIMSFLOW_MAXIMUM_BYTES_BILLED=1073741824", ".env.example", errors)

quality_policy = nil
begin
  quality_policy = YAML.safe_load(read_file("config/data-quality-policy.yml", errors))
rescue Psych::SyntaxError => e
  errors << "data-quality policy must be valid YAML: #{e.message}"
end
if quality_policy.is_a?(Hash)
  unless quality_policy["schema_version"] == "1.0.0" && quality_policy["rule_version"] == "1.0.0"
    errors << "data-quality policy must pin schema and rule version 1.0.0"
  end
  errors << "data-quality policy must remain synthetic_only=true" unless quality_policy["synthetic_only"] == true
  unless quality_policy["evaluation_interval"] == "PT1H"
    errors << "data-quality policy must pin the governed hourly evaluation interval"
  end
  freshness_rule = quality_policy["freshness_rule"]
  unless freshness_rule.is_a?(Hash) &&
         freshness_rule["id"] == "DQ-CMN-015" &&
         freshness_rule["severity"] == "warning" &&
         freshness_rule["disposition"] == "accepted_with_warning"
    errors << "data-quality freshness policy must remain a non-blocking governed warning"
  end
  batch_rules = quality_policy["batch_rules"]
  expected_batch_rules = %w[critical_outcome missing_source reconciliation]
  unless batch_rules.is_a?(Hash) && batch_rules.keys.sort == expected_batch_rules &&
         batch_rules.values.all? { |rule| rule.is_a?(Hash) && rule["disposition"] == "block_batch" }
    errors << "data-quality policy must declare the exact fail-closed batch rule inventory"
  end
  relationship_rules = quality_policy["relationship_rules"]
  relationship_count = if relationship_rules.is_a?(Hash)
                         relationship_rules.values.sum { |targets| targets.is_a?(Hash) ? targets.length : 0 }
                       else
                         0
                       end
  errors << "data-quality policy must map every governed relationship rule" unless relationship_count == 27
else
  errors << "data-quality policy root must be an object"
end

config = read_file("src/claimsflow/config.py", errors)
require_text(config, 'SUPPORTED_ENVIRONMENTS = frozenset({"local", "dev-demo"})', "Python configuration", errors)
require_text(config, 'synthetic_flag != "true"', "Python configuration", errors)
require_text(config, "real data is prohibited", "Python configuration", errors)
require_text(config, "maximum_bytes_billed <= 0", "Python configuration", errors)
require_text(config, '"local": 1_073_741_824', "Python configuration", errors)
require_text(config, '"dev-demo": 10_737_418_240', "Python configuration", errors)
require_text(config, "maximum_bytes_billed > environment_limit", "Python configuration", errors)

logging_config = read_file("src/claimsflow/logging_config.py", errors)
%w[environment_id run_id task_id batch_id publication_id rule_id code_version].each do |field|
  require_text(logging_config, %("#{field}"), "structured logger", errors)
end
reject_text(logging_config, '"claim_payload"', "structured logger", errors)

adapter_boundary = read_file("src/claimsflow/adapters/README.md", errors)
{
  "`if_generation_match=0`" => "create-only Cloud Storage uploads",
  "downloads the exact returned generation" => "generation-pinned Cloud Storage verification",
  "recompute SHA-256 before" => "cloud checksum verification before raw loading",
  "deterministic job IDs" => "replay-safe BigQuery jobs",
  "append-only JSON load jobs" => "append-only BigQuery loads",
  "synthetic-only boundary" => "synthetic-only enforcement",
  "metric or transformation logic in dbt" => "dbt-owned transformation logic",
  "Application Default Credentials only" => "explicit default credential construction",
  "imports, unit tests, and local ingestion perform no cloud write" => "no implicit cloud writes"
}.each do |text, label|
  errors << "adapter boundary must declare #{label}" unless adapter_boundary.include?(text)
end

dbt_project = read_file("analytics/dbt/dbt_project.yml", errors)
DBT_LAYERS.each do |layer|
  require_text(dbt_project, "    #{layer}:\n", "dbt_project.yml", errors)
  require_text(dbt_project, "      +schema: #{layer}", "dbt_project.yml", errors)
end
require_text(dbt_project, "claimsflow_publication_id: ci_phase4a", "dbt_project.yml", errors)
require_text(dbt_project, "claimsflow_validation_ids: [ci_validation_phase4a]", "dbt_project.yml", errors)
require_text(
  dbt_project,
  'claimsflow_code_commit: "0000000000000000000000000000000000000000"',
  "dbt_project.yml",
  errors
)
require_text(dbt_project, "+tags: [validated_staging, phase4a]", "dbt_project.yml", errors)
require_text(dbt_project, "publication_scoped: true", "dbt_project.yml", errors)
require_text(dbt_project, "+tags: [curated_dimensions, phase4b1]", "dbt_project.yml", errors)
require_text(dbt_project, "+tags: [curated_facts, phase4b2]", "dbt_project.yml", errors)
require_text(dbt_project, "owner: ClaimsFlow Analytics Engineering", "dbt_project.yml", errors)

dbt_readme = read_file("analytics/dbt/README.md", errors)
require_text(dbt_readme, "Phase 4A implements the validated staging boundary", "dbt README", errors)
require_text(dbt_readme, "validation-selection fingerprint", "dbt README", errors)
require_text(dbt_readme, "exact `claimsflow_code_commit`", "dbt README", errors)
require_text(dbt_readme, "Phase 4B.1", "dbt README", errors)
require_text(dbt_readme, "effective-dated", "dbt README", errors)
require_text(dbt_readme, "Phase 4B.2", "dbt README", errors)
require_text(dbt_readme, "five publication-isolated curated facts", "dbt README", errors)
reject_text(dbt_project, "raw_source", "dbt_project.yml", errors)

sql_models = Dir.glob(File.join(ROOT, "analytics/dbt/models/**/*.sql"))
expected_staging_models = ["stg_validated_records", *STAGING_MODELS.values].map do |model|
  File.join(ROOT, "analytics/dbt/models/staging/#{model}.sql")
end
expected_curated_models = CURATED_DIMENSION_MODELS.map do |model|
  File.join(ROOT, "analytics/dbt/models/curated/dimensions/#{model}.sql")
end
expected_curated_fact_models = CURATED_FACT_MODELS.map do |model|
  File.join(ROOT, "analytics/dbt/models/curated/facts/#{model}.sql")
end
expected_publication_models = PUBLICATION_MODELS.map do |model|
  File.join(ROOT, "analytics/dbt/models/publication/#{model}.sql")
end
expected_sql_models = (
  expected_staging_models +
  expected_curated_models +
  expected_curated_fact_models +
  expected_publication_models
).sort
unless sql_models.sort == expected_sql_models
  missing = expected_sql_models - sql_models
  unexpected = sql_models - expected_sql_models
  errors << "dbt governed model inventory must contain only approved Phase 4A and Phase 4B models: " \
            "missing=#{missing.map { |path| relative(path) }.sort} " \
            "unexpected=#{unexpected.map { |path| relative(path) }.sort}"
end

base_staging = read_file("analytics/dbt/models/staging/stg_validated_records.sql", errors)
{
  "source('claimsflow_validated', 'records')" => "validated record source",
  "source('claimsflow_audit', 'quality_runs')" => "quality-run source",
  "claimsflow_validation_filter" => "immutable validation allowlist",
  "publication_allowed is true" => "approved publication gate",
  "reconciled is true" => "quality reconciliation gate",
  "decision = 'approved'" => "approved quality decision",
  "disposition in ('accepted', 'accepted_with_warning')" => "publishable disposition boundary",
  "computed_record_evidence_sha256" => "recomputed record evidence",
  "normalized_payload_sha256 is distinct from computed_normalized_payload_sha256" => "canonical normalized-payload digest gate",
  "quality.validated_record_set_sha256 = record_set.computed_record_set_sha256" => "immutable validated record-set digest",
  "mismatched_record_evidence_count = 0" => "record-evidence reconciliation gate"
}.each do |text, label|
  errors << "dbt validated staging base must declare #{label}" unless base_staging.include?(text)
end

STAGING_MODELS.each do |identity, model|
  model_sql = read_file("analytics/dbt/models/staging/#{model}.sql", errors)
  require_text(model_sql, "claimsflow_stage_validated", "dbt #{model}", errors)
  require_text(model_sql, "source_identity='#{identity}'", "dbt #{model}", errors)
  reject_text(model_sql, "source(", "dbt #{model} validated boundary", errors)
end

publication_scope = read_file("analytics/dbt/macros/publication_scope.sql", errors)
{
  "target.name != 'ci'" => "non-CI publication-ID override",
  "non-empty list of immutable quality validation IDs" => "validation allowlist",
  "modules.re.fullmatch" => "safe identifier validation",
  "unique_ids | sort" => "deterministic validation allowlist",
  "local_md5(canonical_selection)" => "deterministic candidate-selection fingerprint",
  "claimsflow_code_commit" => "exact code-commit binding",
  "non-placeholder claimsflow_code_commit" => "non-CI code-commit override",
  "local_md5(canonical_build)" => "deterministic candidate-build fingerprint"
}.each do |text, label|
  errors << "dbt publication-scope macro must declare #{label}" unless publication_scope.include?(text)
end

alias_macro = read_file("analytics/dbt/macros/generate_alias_name.sql", errors)
require_text(alias_macro, "publication_scoped", "dbt publication alias macro", errors)
require_text(
  alias_macro,
  "base_alias }}__{{ claimsflow_publication_id()",
  "dbt publication-scoped physical aliases",
  errors
)
require_text(
  alias_macro,
  "claimsflow_publication_selection_fingerprint()",
  "dbt validation-bound physical aliases",
  errors
)
require_text(
  alias_macro,
  "claimsflow_candidate_build_fingerprint()",
  "dbt code-bound physical aliases",
  errors
)

staging_macro = read_file("analytics/dbt/macros/stage_validated.sql", errors)
{
  "ref('stg_validated_records')" => "validated-only model dependency",
  "safe_cast" => "type-safe scalar projection",
  "cast([] as array<string>)" => "typed empty string lists",
  "normalized_payload_canonical_json" => "verified canonical payload projection",
  "claimsflow_normalized_payload_sha256" => "canonical payload checksum",
  "unsupported validated source type" => "fail-closed type policy"
}.each do |text, label|
  errors << "dbt staging macro must declare #{label}" unless staging_macro.include?(text)
end

begin
  staging_sources_text = read_file("analytics/dbt/models/staging/_sources.yml", errors)
  staging_sources = YAML.safe_load(staging_sources_text)
  source_inventory = staging_sources.fetch("sources", []).to_h do |source|
    [source.fetch("name"), source.fetch("tables", []).map { |table| table.fetch("name") }.sort]
  end
  unless source_inventory == {
    "claimsflow_audit" => ["quality_runs"],
    "claimsflow_validated" => ["records"]
  }
    errors << "dbt Phase 4A sources must contain only validated records and quality runs"
  end
  %w[
    record_evidence_sha256
    normalized_payload_canonical_json
    normalized_payload_sha256
    validated_record_evidence_algorithm
    validated_record_set_algorithm
    validated_record_count
    validated_record_set_sha256
  ].each do |field|
    errors << "dbt Phase 4A source interface must declare #{field}" unless staging_sources_text.include?(field)
  end
rescue Psych::SyntaxError, KeyError, NoMethodError => e
  errors << "dbt Phase 4A sources must be valid governed YAML: #{e.message}"
end

begin
  staging_properties = YAML.safe_load(read_file("analytics/dbt/models/staging/_staging.yml", errors))
  property_models = staging_properties.fetch("models", [])
  property_names = property_models.map { |model| model.fetch("name") }
  unless property_names.sort == STAGING_MODELS.values.sort
    errors << "dbt Phase 4A properties must document exactly fourteen typed staging models"
  end
  property_models.each do |model|
    metadata = model.dig("config", "meta")
    unless model.dig("config", "access") == "protected" && model.dig("config", "contract", "enforced") == true &&
           metadata.is_a?(Hash) && STAGING_MODELS[metadata["source_identity"]] == model["name"] &&
           metadata["publication_scoped"] == true && model.fetch("columns", []).all? do |column|
             column["name"].is_a?(String) && column["data_type"].is_a?(String) &&
               column["description"].is_a?(String) && !column["description"].empty?
           end
      errors << "dbt Phase 4A model properties must enforce protected documented publication-scoped contracts"
    end
  end
rescue Psych::SyntaxError, KeyError, NoMethodError => e
  errors << "dbt Phase 4A properties must be valid governed YAML: #{e.message}"
end

staging_reconciliation = read_file(
  "analytics/dbt/tests/staging_reconciles_to_typed_models.sql",
  errors
)
STAGING_MODELS.values.each do |model|
  require_text(staging_reconciliation, "'#{model}'", "dbt staging reconciliation", errors)
end
require_text(
  read_file("analytics/dbt/tests/staging_reconciles_to_quality_counts.sql", errors),
  "accepted + warned as expected_validated_rows",
  "dbt staging count reconciliation",
  errors
)
validated_record_set_test = read_file(
  "analytics/dbt/tests/staging_reconciles_to_validated_record_set.sql",
  errors
)
{
  "claimsflow_validated_record_evidence_sha256" => "recomputed row evidence",
  "claimsflow_normalized_payload_sha256" => "recomputed canonical payload evidence",
  "normalized_payload_sha256 is distinct from computed_normalized_payload_sha256" => "canonical payload digest comparison",
  "validated_record_set_sha256\n    is distinct from record_set.computed_record_set_sha256" => "record-set digest comparison",
  "mismatched_record_evidence_count is distinct from 0" => "per-record evidence comparison"
}.each do |text, label|
  errors << "dbt validated record-set test must declare #{label}" unless validated_record_set_test.include?(text)
end
require_text(
  read_file("analytics/dbt/tests/staging_publication_scope.sql", errors),
  "claimsflow_validation_ids()",
  "dbt staging candidate-scope test",
  errors
)
require_text(
  read_file("analytics/dbt/tests/staging_requires_every_validation.sql", errors),
  "approved_row_count",
  "dbt required-validation evidence test",
  errors
)
%w[
  staging_publication_scope.sql
  staging_reconciles_to_quality_counts.sql
  staging_reconciles_to_typed_models.sql
  staging_reconciles_to_validated_record_set.sql
  staging_requires_every_validation.sql
].each do |filename|
  require_text(
    read_file("analytics/dbt/tests/#{filename}", errors),
    "config(tags=['validated_staging', 'phase4a'])",
    "dbt validated-staging full-candidate selector",
    errors
  )
end

properties_generator = read_file("scripts/render_dbt_staging_properties.py", errors)
require_text(properties_generator, 'parser.add_argument("--check"', "dbt properties generator", errors)
require_text(properties_generator, "if set(result) != set(MODEL_NAMES)", "dbt properties generator", errors)

curated_macro = read_file("analytics/dbt/macros/curated_dimensions.sql", errors)
{
  "claimsflow_dimension_key" => "deterministic dimension-key helper",
  "to_hex(" => "hex-encoded key output",
  "sha256(" => "SHA-256 dimension keys",
  "to_json_string(" => "unambiguous structured key serialization",
  "claimsflow_effective_dimension" => "effective-dated dimension helper",
  "ref(source_model)" => "validated staging dependency",
  "claimsflow_candidate_dates" => "candidate date-source inventory",
  "claimsflow_max_date_spine_days" => "bounded candidate date spine"
}.each do |text, label|
  errors << "dbt curated dimension macro must declare #{label}" unless curated_macro.include?(text)
end

CURATED_DIMENSION_MODELS.each do |model|
  model_sql = read_file("analytics/dbt/models/curated/dimensions/#{model}.sql", errors)
  reject_text(model_sql, "source(", "dbt #{model} validated boundary", errors)
  reject_text(model_sql, "quarantine", "dbt #{model} validated boundary", errors)
end
%w[denial_reason diagnosis facility payer procedure provider].each do |entity|
  require_text(
    read_file("analytics/dbt/models/curated/dimensions/dim_#{entity}.sql", errors),
    "claimsflow_effective_dimension",
    "dbt dim_#{entity}",
    errors
  )
end
plan_sql = read_file("analytics/dbt/models/curated/dimensions/dim_plan.sql", errors)
require_text(plan_sql, "ref('dim_payer')", "dbt conformed plan-to-payer relationship", errors)
require_text(plan_sql, "date '9999-12-31'", "dbt effective plan-to-payer relationship", errors)
patient_sql = read_file("analytics/dbt/models/curated/dimensions/dim_patient.sql", errors)
require_text(patient_sql, "ref('stg_eligibility')", "dbt patient validated dependency", errors)
require_text(patient_sql, "array_agg(distinct validation_id", "dbt patient lineage rollup", errors)
date_sql = read_file("analytics/dbt/models/curated/dimensions/dim_date.sql", errors)
require_text(date_sql, "claimsflow_candidate_dates", "dbt date candidate coverage", errors)
require_text(date_sql, "generate_date_array", "dbt continuous date spine", errors)

begin
  curated_properties = YAML.safe_load(
    read_file("analytics/dbt/models/curated/dimensions/_dimensions.yml", errors)
  )
  curated_property_models = curated_properties.fetch("models", [])
  curated_property_names = curated_property_models.map { |model| model.fetch("name") }
  unless curated_property_names.sort == CURATED_DIMENSION_MODELS.sort
    errors << "dbt Phase 4B.1 properties must document exactly nine curated dimensions"
  end
  curated_property_models.each do |model|
    metadata = model.dig("config", "meta")
    unless model.dig("config", "access") == "protected" &&
           model.dig("config", "contract", "enforced") == true &&
           metadata.is_a?(Hash) && metadata["owner"] == "ClaimsFlow Analytics Engineering" &&
           metadata["materialization"] == "table" &&
           metadata["publication_scoped"] == true && metadata["grain"].is_a?(String) &&
           metadata["purpose"].is_a?(String) && metadata["history_strategy"].is_a?(String) &&
           metadata["source_models"].is_a?(Array) && model.fetch("columns", []).all? do |column|
             column["name"].is_a?(String) && column["data_type"].is_a?(String) &&
               column["description"].is_a?(String) && !column["description"].empty?
           end
      errors << "dbt Phase 4B.1 model properties must enforce documented publication-scoped contracts"
    end
  end
rescue Psych::SyntaxError, KeyError, NoMethodError => e
  errors << "dbt Phase 4B.1 properties must be valid governed YAML: #{e.message}"
end

curated_properties_generator = read_file(
  "scripts/render_dbt_curated_dimension_properties.py",
  errors
)
require_text(
  curated_properties_generator,
  'parser.add_argument("--check"',
  "dbt curated properties generator",
  errors
)
require_text(
  curated_properties_generator,
  "EFFECTIVE_DIMENSIONS",
  "dbt curated properties generator",
  errors
)

curated_publication_test = read_file(
  "analytics/dbt/tests/curated_dimension_publication_scope.sql",
  errors
)
CURATED_DIMENSION_MODELS.each do |model|
  require_text(curated_publication_test, "'#{model}'", "dbt curated publication scope", errors)
end
curated_reconciliation_test = read_file(
  "analytics/dbt/tests/curated_dimension_reconciliation.sql",
  errors
)
(CURATED_DIMENSION_MODELS - ["dim_date"]).each do |model|
  require_text(curated_reconciliation_test, "'#{model}'", "dbt curated reconciliation", errors)
end
curated_history_test = read_file(
  "analytics/dbt/tests/curated_dimension_history_integrity.sql",
  errors
)
(CURATED_DIMENSION_MODELS - %w[dim_date dim_patient]).each do |model|
  require_text(curated_history_test, "'#{model}'", "dbt curated history integrity", errors)
end
require_text(
  curated_history_test,
  "overlapping_history_versions",
  "dbt curated history integrity",
  errors
)
require_text(
  read_file("analytics/dbt/tests/curated_plan_payer_effective_relationship.sql", errors),
  "payer.payer_dimension_id is null",
  "dbt effective plan-to-payer relationship",
  errors
)
curated_date_test = read_file("analytics/dbt/tests/curated_date_coverage.sql", errors)
require_text(curated_date_test, "claimsflow_candidate_dates", "dbt date coverage", errors)
require_text(curated_date_test, "except distinct", "dbt date coverage", errors)
curated_date_span_test = read_file("analytics/dbt/tests/curated_date_span_bound.sql", errors)
require_text(curated_date_span_test, "date_spine_days", "dbt bounded date spine", errors)
%w[
  curated_date_coverage.sql
  curated_date_span_bound.sql
  curated_dimension_history_integrity.sql
  curated_dimension_publication_scope.sql
  curated_dimension_reconciliation.sql
  curated_plan_payer_effective_relationship.sql
].each do |filename|
  require_text(
    read_file("analytics/dbt/tests/#{filename}", errors),
    "config(tags=['curated_dimensions', 'phase4b1'])",
    "dbt curated-dimension full-candidate selector",
    errors
  )
end
require_text(
  curated_date_span_test,
  "config(tags=['curated_dimensions', 'phase4b1'])",
  "dbt curated date-span selector",
  errors
)
require_text(
  curated_date_span_test,
  "claimsflow_max_date_spine_days",
  "dbt bounded date spine",
  errors
)

curated_fact_macro = read_file("analytics/dbt/macros/curated_facts.sql", errors)
{
  "claimsflow_fact_key" => "deterministic fact-key helper",
  "claimsflow_dimension_key" => "shared structured SHA-256 serialization",
  "claimsflow_date_dimension_id" => "deterministic date-key helper",
  "format_date('%Y%m%d'" => "YYYYMMDD date-key convention",
  "cast(null as int64)" => "nullable date-role behavior"
}.each do |text, label|
  errors << "dbt curated fact macro must declare #{label}" unless curated_fact_macro.include?(text)
end

CURATED_FACT_MODELS.each do |model|
  model_sql = read_file("analytics/dbt/models/curated/facts/#{model}.sql", errors)
  require_text(model_sql, "claimsflow_fact_key", "dbt #{model}", errors)
  require_text(model_sql, "partition_by", "dbt #{model} partition policy", errors)
  reject_text(model_sql, "source(", "dbt #{model} validated boundary", errors)
  reject_text(model_sql, "quarantine", "dbt #{model} validated boundary", errors)
end
require_text(
  read_file("analytics/dbt/models/curated/facts/fact_claim_line.sql", errors),
  "diagnosis_resolutions",
  "dbt ordered line-diagnosis conformance",
  errors
)
require_text(
  read_file("analytics/dbt/models/curated/facts/fact_payment.sql", errors),
  "signed_amount",
  "dbt governed payment sign",
  errors
)
require_text(
  read_file("analytics/dbt/models/curated/facts/fact_payment.sql", errors),
  "remittance_source_validated_record_id",
  "dbt resolved payment remittance",
  errors
)

begin
  curated_fact_properties = YAML.safe_load(
    read_file("analytics/dbt/models/curated/facts/_facts.yml", errors)
  )
  curated_fact_property_models = curated_fact_properties.fetch("models", [])
  curated_fact_property_names = curated_fact_property_models.map { |model| model.fetch("name") }
  unless curated_fact_property_names.sort == CURATED_FACT_MODELS.sort
    errors << "dbt Phase 4B.2 properties must document exactly five curated facts"
  end
  curated_fact_property_models.each do |model|
    metadata = model.dig("config", "meta")
    unless model.dig("config", "access") == "protected" &&
           model.dig("config", "contract", "enforced") == true &&
           metadata.is_a?(Hash) && metadata["owner"] == "ClaimsFlow Analytics Engineering" &&
           metadata["materialization"] == "table" && metadata["publication_scoped"] == true &&
           metadata["grain"].is_a?(String) && metadata["purpose"].is_a?(String) &&
           metadata["partition_by"].is_a?(String) && metadata["cluster_by"].is_a?(Array) &&
           metadata["source_models"].is_a?(Array) && metadata["financial_fields"].is_a?(Array) &&
           model.fetch("columns", []).all? do |column|
             column["name"].is_a?(String) && column["data_type"].is_a?(String) &&
               column["description"].is_a?(String) && !column["description"].empty?
           end
      errors << "dbt Phase 4B.2 model properties must enforce documented publication-scoped contracts"
    end
  end
rescue Psych::SyntaxError, KeyError, NoMethodError => e
  errors << "dbt Phase 4B.2 properties must be valid governed YAML: #{e.message}"
end

curated_fact_properties_generator = read_file(
  "scripts/render_dbt_curated_fact_properties.py",
  errors
)
require_text(
  curated_fact_properties_generator,
  'parser.add_argument("--check"',
  "dbt curated fact properties generator",
  errors
)
require_text(
  curated_fact_properties_generator,
  "FACT_SPECS",
  "dbt curated fact properties generator",
  errors
)

curated_fact_tests = {
  "publication scope" => "curated_fact_publication_scope.sql",
  "source reconciliation" => "curated_fact_source_reconciliation.sql",
  "parent relationships" => "curated_fact_parent_relationships.sql",
  "effective dimensions" => "curated_fact_effective_dimension_relationships.sql",
  "date keys" => "curated_fact_date_keys.sql",
  "line diagnoses" => "curated_fact_line_diagnosis_relationships.sql",
  "financial integrity" => "curated_fact_financial_integrity.sql"
}
curated_fact_test_text = curated_fact_tests.to_h do |label, filename|
  text = read_file("analytics/dbt/tests/#{filename}", errors)
  require_text(
    text,
    "config(tags=['curated_facts', 'phase4b2'])",
    "dbt curated fact #{label} selector",
    errors
  )
  [label, text]
end
CURATED_FACT_MODELS.each do |model|
  require_text(
    curated_fact_test_text["publication scope"],
    "'#{model}'",
    "dbt curated fact publication scope",
    errors
  )
  require_text(
    curated_fact_test_text["source reconciliation"],
    "'#{model}'",
    "dbt curated fact source reconciliation",
    errors
  )
end
{
  "original_claim" => "parent claim lineage",
  "reversed_payment" => "payment reversal lineage",
  "remittance_source_validated_record_id" => "payment remittance lineage"
}.each do |text, label|
  require_text(curated_fact_test_text["parent relationships"], text, label, errors)
end
require_text(
  curated_fact_test_text["effective dimensions"],
  "dimension.valid_to",
  "dbt fact effective-date relationship",
  errors
)
require_text(
  curated_fact_test_text["line diagnoses"],
  "safe_offset(diagnosis_offset)",
  "dbt ordered diagnosis relationship",
  errors
)
require_text(
  curated_fact_test_text["financial integrity"],
  "denial_total_recovery",
  "dbt fact financial recovery control",
  errors
)
require_text(
  curated_fact_test_text["financial integrity"],
  "remittance_control",
  "dbt fact remittance financial control",
  errors
)

dbt_schema_macro = read_file("analytics/dbt/macros/generate_schema_name.sql", errors)
{
  "'staging': 'claimsflow_curated'" => "private staging physical dataset",
  "'intermediate': 'claimsflow_curated'" => "private intermediate physical dataset",
  "'curated': 'claimsflow_curated'" => "curated physical dataset",
  "'semantic': 'claimsflow_semantic'" => "semantic physical dataset",
  "'operational': 'claimsflow_operational'" => "operational physical dataset",
  "'audit': 'claimsflow_audit'" => "audit physical dataset",
  "'dbt_test__audit': 'claimsflow_audit'" => "dbt test audit physical dataset",
  "exceptions.raise_compiler_error" => "fail-closed unapproved-schema policy"
}.each do |text, label|
  errors << "dbt dev/demo schema mapping must declare #{label}" unless dbt_schema_macro.include?(text)
end

dbt_profile = read_file("config/dbt/profiles.yml", errors)
require_text(dbt_profile, "method: oauth", "dbt profile", errors)
require_text(dbt_profile, "maximum_bytes_billed: 1073741824", "dbt profile", errors)
require_text(
  dbt_profile,
  "dataset: \"{{ env_var('CLAIMSFLOW_DBT_DATASET', 'claimsflow_curated') }}\"",
  "dbt dev/demo profile",
  errors
)
%w[keyfile keyfile_json private_key client_secret password].each do |secret_method|
  reject_text(dbt_profile, secret_method, "dbt profile", errors)
end

compose = read_file("compose.yaml", errors)
require_text(compose, "AIRFLOW_IMAGE: #{AIRFLOW_IMAGE}", "compose.yaml", errors)
require_text(compose, 'CLAIMSFLOW_SYNTHETIC_ONLY: "true"', "compose.yaml", errors)
require_text(compose, "command: standalone", "compose.yaml", errors)
require_text(compose, '"127.0.0.1:8080:8080"', "compose.yaml", errors)
%w[GOOGLE_APPLICATION_CREDENTIALS service_account.json private_key client_secret].each do |secret_value|
  reject_text(compose, secret_value, "compose.yaml", errors)
end

dockerfile = read_file("orchestration/airflow/Dockerfile", errors)
require_text(dockerfile, "ARG AIRFLOW_IMAGE=#{AIRFLOW_IMAGE}", "Airflow Dockerfile", errors)
require_text(dockerfile, "USER airflow", "Airflow Dockerfile", errors)
reject_text(dockerfile, "pip install", "Airflow Dockerfile", errors)

dockerignore = read_file(".dockerignore", errors)
%w[
  .env
  .env.*
  **/*.tfstate
  **/*.tfvars
  **/*.tfvars.json
  **/*.auto.tfvars
  **/*.auto.tfvars.json
  !**/*.tfvars.example
  orchestration/airflow/db
].each do |entry|
  require_text(dockerignore, entry, ".dockerignore", errors)
end
gitignore = read_file(".gitignore", errors)
require_text(gitignore, "orchestration/airflow/db/", ".gitignore", errors)
require_text(gitignore, "config/dbt/.user.yml", ".gitignore", errors)
%w[*.tfvars *.tfvars.json *.auto.tfvars *.auto.tfvars.json !*.tfvars.example].each do |entry|
  require_text(gitignore, entry, ".gitignore Terraform variable policy", errors)
end

dag = read_file("orchestration/airflow/dags/claimsflow_batch.py", errors)
task_declarations = dag.scan(/^    ([a-z_]+) = EmptyOperator\(\s*task_id="([a-z_]+)"/m)
declared_variables = task_declarations.map(&:first)
declared_task_ids = task_declarations.map(&:last)
errors << "Airflow DAG must declare exactly the governed task IDs" unless declared_task_ids == DAG_TASKS
errors << "Airflow DAG task variables must match their task IDs" unless task_declarations.all? { |variable, task_id| variable == task_id }

chain = dag[/^    \(\n(?<body>.*?)^    \)$/m, :body]
chain_tasks = chain&.scan(/^        (?:>> )?([a-z_]+)$/)&.flatten
errors << "Airflow DAG must declare the exact fail-closed dependency chain" unless chain_tasks == DAG_TASKS
{
  "schedule=None" => "manual Phase 1 schedule",
  "catchup=False" => "disabled catchup",
  "max_active_runs=1" => "bounded active runs",
  "max_active_tasks=4" => "bounded active tasks",
  '"execution_timeout"' => "task timeout",
  '"on_failure_callback"' => "failure callback",
  '"retry_exponential_backoff"' => "retry backoff",
  '"trigger_rule": "all_success"' => "fail-closed trigger rule",
  "retries=0" => "non-blind publication retry policy"
}.each do |text, label|
  errors << "Airflow DAG must declare #{label}" unless dag.include?(text)
end
unless dag.match?(/advance_publication = EmptyOperator\(\s*task_id="advance_publication",\s*retries=0,\s*\)/m)
  errors << "Airflow DAG must scope the zero-retry publication policy to advance_publication"
end
require_text(dag, "never serialize XCom values or row payloads", "Airflow failure callback", errors)

dag_policy = read_file("orchestration/airflow/policy/validate_dag.py", errors)
{
  "DagBag" => "runtime DAG loading",
  "actual_edges != EXPECTED_EDGES" => "exact effective-edge validation",
  "task.trigger_rule != TriggerRule.ALL_SUCCESS" => "effective fail-closed trigger validation",
  'task.task_id == "advance_publication"' => "effective publication retry validation",
  "task.on_failure_callback is None" => "effective failure-callback validation"
}.each do |text, label|
  errors << "Airflow runtime policy must declare #{label}" unless dag_policy.include?(text)
end

terraform_versions = read_file("infra/terraform/modules/foundation/versions.tf", errors)
require_text(terraform_versions, 'required_version = "~> 1.15.0"', "foundation versions", errors)
require_text(terraform_versions, 'version = "= 7.44.0"', "foundation versions", errors)

terraform_foundation = read_file("infra/terraform/modules/foundation/main.tf", errors)
terraform_variables = read_file("infra/terraform/modules/foundation/variables.tf", errors)
DATASET_LAYERS.each do |layer|
  require_text(terraform_foundation, %(    "#{layer}",), "foundation datasets", errors)
end
WORKLOAD_ACCOUNTS.each do |account|
  unless terraform_foundation.match?(/^    #{Regexp.escape(account)}\s+=/)
    errors << "foundation workload identities must contain #{account.inspect}"
  end
end
{
  "force_destroy               = false" => "non-destructive bucket",
  'public_access_prevention    = "enforced"' => "public-access prevention",
  "uniform_bucket_level_access = true" => "uniform bucket access",
  "retention_period = 34560000" => "400-day retention floor",
  "retention_duration_seconds = 604800" => "soft deletion",
  "delete_contents_on_destroy = false" => "non-destructive datasets",
  'role    = "roles/bigquery.jobUser"' => "bounded query execution",
  'resource "google_storage_bucket_iam_member" "ingestion_object_viewer"' => "landing checksum read access",
  'resource "google_billing_budget" "dev_demo"' => "cost budget",
  '"billingbudgets.googleapis.com"' => "Cloud Billing Budget API",
  'resource "google_iam_workload_identity_pool" "github"' => "Workload Identity Federation",
  "assertion.ref == 'refs/heads/main'" => "branch-restricted federation",
  "assertion.repository_id == '${var.github_repository_id}'" => "immutable repository-ID federation",
  "assertion.repository_owner_id == '${var.github_repository_owner_id}'" => "immutable owner-ID federation",
  "assertion.job_workflow_ref == '${var.github_workflow_ref}'" => "workflow-restricted federation",
  "assertion.environment == '${var.github_environment}'" => "environment-restricted federation",
  "attribute.repository_id/${var.github_repository_id}" => "immutable repository-ID principal"
}.each do |text, label|
  errors << "Terraform foundation must declare #{label}" unless terraform_foundation.include?(text)
end

require_text(
  terraform_foundation,
  'for_each = toset(["ingestion", "transformation", "orchestration", "bi", "auditor"])',
  "Terraform BigQuery job execution policy",
  errors
)
unless terraform_foundation.match?(/orchestration_audit = \{\s*dataset = "audit"\s*role\s+= "roles\/bigquery\.dataEditor"\s*account = "orchestration"\s*\}/m)
  errors << "Terraform foundation must grant orchestration exact audit write access"
end
if terraform_foundation.match?(/orchestration_object_viewer|workload\["orchestration"\].*roles\/storage\.objectViewer/m)
  errors << "Terraform foundation must not grant orchestration landing-object read access"
end
if terraform_foundation.match?(/resource "google_billing_budget" "dev_demo" \{\s*count\s*=/m)
  errors << "Terraform dev/demo budget must be mandatory"
end
caller_labels_position = terraform_foundation.index("var.labels")
invariant_labels_position = terraform_foundation.index('application    = "claimsflow"')
unless caller_labels_position && invariant_labels_position && caller_labels_position < invariant_labels_position
  errors << "Terraform invariant labels must override caller labels"
end
require_text(terraform_variables, "labels cannot override ClaimsFlow reserved governance keys", "Terraform label validation", errors)
require_text(terraform_variables, "github_workflow_ref must belong to github_repository", "Terraform workflow/repository validation", errors)
unless terraform_variables.match?(/monthly_budget_usd <= 100\s*&&/)
  errors << "Terraform variables must declare bounded budget validation"
end
%w[
  billing_account_id
  github_repository
  github_repository_id
  github_repository_owner_id
  github_workflow_ref
  github_environment
].each do |variable|
  require_text(terraform_variables, %(variable "#{variable}"), "Terraform required deployment inputs", errors)
end
{
  '^[A-Z0-9]{6}-[A-Z0-9]{6}-[A-Z0-9]{6}$' => "billing-account format validation",
  '^[0-9]+$' => "immutable numeric GitHub ID validation",
  "github/workflows/" => "GitHub workflow-ref validation",
  "refs/heads/main" => "workflow main-ref validation"
}.each do |text, label|
  errors << "Terraform variables must declare #{label}" unless terraform_variables.include?(text)
end

dev_versions = read_file("infra/terraform/environments/dev-demo/versions.tf", errors)
require_text(dev_versions, 'backend "gcs" {}', "dev/demo Terraform root", errors)
local_root = read_file("infra/terraform/environments/local/main.tf", errors)
require_text(local_root, 'resource "terraform_data" "claimsflow_local_boundary"', "local Terraform root", errors)
require_text(local_root, "prevent_destroy = true", "local Terraform root", errors)

schema = nil
example = nil
begin
  schema = JSON.parse(read_file("config/release-manifest.schema.json", errors))
rescue JSON::ParserError => e
  errors << "Release manifest schema must be valid JSON: #{e.message}"
end
begin
  example = JSON.parse(read_file("config/release-manifest.example.json", errors))
rescue JSON::ParserError => e
  errors << "Release manifest example must be valid JSON: #{e.message}"
end
if schema && example
  required = schema.fetch("required", [])
  missing = required - example.keys
  errors << "Release manifest example is missing schema fields: #{missing.join(', ')}" unless missing.empty?
  errors << "Release manifest example must be synthetic_only=true" unless example["synthetic_only"] == true
  versions = example.fetch("component_versions", {})
  expected_versions = {
    "python" => "3.12",
    "dbt_core" => "1.12.2",
    "dbt_bigquery" => "1.12.0",
    "airflow" => "3.3.1",
    "terraform" => "1.15.8",
    "google_provider" => "7.44.0"
  }
  errors << "Release manifest component versions must match the scaffold" unless versions == expected_versions

  contract_versions = Dir.glob(File.join(ROOT, "contracts/source-data/*.yml")).map do |path|
    File.read(path)[/^contract_version:\s*(\S+)/, 1]
  end.compact.uniq
  dictionary_versions = Dir.glob(File.join(ROOT, "contracts/metrics/*.yml")).map do |path|
    File.read(path)[/^dictionary_version:\s*(\S+)/, 1]
  end.compact.uniq
  unless contract_versions == [example["contract_version"]]
    errors << "Release manifest contract_version must match every governed source contract"
  end
  unless dictionary_versions == [example["dictionary_version"]]
    errors << "Release manifest dictionary_version must match every governed metric contract"
  end

  dependency_locks = example["dependency_locks"]
  unless dependency_locks.is_a?(Array) && dependency_locks.all? { |path| path.is_a?(String) && File.file?(File.join(ROOT, path)) }
    errors << "Release manifest dependency_locks must reference existing repository files"
  end
end

release_test = read_file("tests/unit/test_release_manifest.py", errors)
require_text(release_test, "Draft202012Validator.check_schema", "release-manifest tests", errors)
require_text(release_test, "FormatChecker", "release-manifest tests", errors)
require_text(release_test, "additional-property", "release-manifest tests", errors)

workflow = read_file(".github/workflows/project-foundation.yml", errors)
CI_PATHS.each { |path| require_text(workflow, %(      - "#{path}"), "foundation workflow paths", errors) }
{
  'version: "0.12.4"' => "uv version",
  "uv sync --locked --all-groups" => "locked dependency installation",
  "ruff check ." => "Python lint",
  "ruff format --check ." => "Python format check",
  "mypy" => "Python type check",
  "pytest" => "Python unit tests",
  "python scripts/render_dbt_staging_properties.py --check" => "generated dbt staging properties",
  "python scripts/render_dbt_curated_dimension_properties.py --check" => "generated dbt curated dimension properties",
  "python scripts/render_dbt_curated_fact_properties.py --check" => "generated dbt curated fact properties",
  "dbt parse" => "dbt parse",
  "docker compose config --quiet" => "Compose validation",
  "docker compose build airflow" => "Airflow image build",
  "python /opt/claimsflow/airflow_policy/validate_dag.py" => "effective Airflow DAG policy",
  'terraform_version: "1.15.8"' => "Terraform version",
  "terraform fmt -check" => "Terraform format check",
  "terraform -chdir=infra/terraform/environments/local validate" => "local Terraform validation",
  "terraform -chdir=infra/terraform/environments/dev-demo validate" => "dev/demo Terraform validation",
  "GITHUB_TOKEN" => "secret-scan token"
}.each do |text, label|
  errors << "Foundation workflow must run #{label}" unless workflow.include?(text)
end
ACTION_PINS.each do |action, sha|
  require_text(workflow, "#{action}@#{sha}", "foundation workflow immutable action pins", errors)
end
workflow.scan(/uses:\s+([^\s#]+)/).flatten.each do |reference|
  next if reference.match?(/@[0-9a-f]{40}\z/)

  errors << "Foundation workflow action references must use immutable commit SHAs: #{reference}"
end

development_docs = read_file("docs/development/README.md", errors)
%w[bootstrap check airflow-up terraform-validate].each do |command|
  require_text(development_docs, "make #{command}", "development guide", errors)
end
require_text(development_docs, "terraform apply", "development guide", errors)
require_text(development_docs, "claimsflow validate", "development guide", errors)
require_text(development_docs, "dbt validated staging", "development guide", errors)
require_text(development_docs, "dbt curated dimensions", "development guide", errors)
require_text(development_docs, "dbt curated facts", "development guide", errors)

dbt_staging_docs = read_file("docs/development/dbt-validated-staging.md", errors)
{
  "claimsflow_publication_id" => "candidate publication identifier",
  "claimsflow_validation_ids" => "immutable validation allowlist",
  "claimsflow_code_commit" => "exact code commit",
  "selection-fingerprint" => "candidate isolation",
  "build-fingerprint" => "immutable build isolation",
  "validated_record_set_sha256" => "cryptographic record-set binding",
  "fourteen typed models" => "complete staging identity inventory",
  "accepted plus warned" => "quality count reconciliation",
  "Phase 4B" => "next milestone boundary"
}.each do |text, label|
  errors << "dbt validated-staging guide must declare #{label}" unless dbt_staging_docs.include?(text)
end

dbt_curated_docs = read_file("docs/development/dbt-curated-dimensions.md", errors)
{
  "Phase 4B.1" => "curated-dimension milestone",
  "nine conformed dimensions" => "complete dimension inventory",
  "effective-dated" => "history-preserving dimensions",
  "publication" => "candidate isolation",
  "dim_plan" => "plan-to-payer conformance",
  "dim_date" => "continuous calendar coverage",
  "--target dev_demo" => "configured dev/demo target",
  "Phase 4B.2" => "next milestone boundary"
}.each do |text, label|
  errors << "dbt curated-dimension guide must declare #{label}" unless dbt_curated_docs.include?(text)
end

dbt_curated_fact_docs = read_file("docs/development/dbt-curated-facts.md", errors)
{
  "Phase 4B.2" => "curated-fact milestone",
  "five curated facts" => "complete fact inventory",
  "deterministic SHA-256" => "deterministic fact keys",
  "effective" => "effective-dated dimension relationships",
  "zero USD tolerance" => "exact financial reconciliation",
  "--select tag:validated_staging tag:curated_dimensions tag:curated_facts" => "complete release selector",
  "Phase 4B.3" => "next milestone boundary"
}.each do |text, label|
  errors << "dbt curated-fact guide must declare #{label}" unless dbt_curated_fact_docs.include?(text)
end

safe_publication_docs = read_file("docs/development/safe-publication.md", errors)
{
  "complete business-key/content-hash inventory" => "complete candidate inventory",
  "publication_reservation_locks" => "serialized publication reservation",
  "preseeded" => "preseeded active-pointer control rows",
  "code-bound build fingerprint" => "immutable physical build alias",
  "synthetic GCP concurrency exercise" => "explicit live concurrency gate"
}.each do |text, label|
  errors << "safe-publication guide must declare #{label}" unless safe_publication_docs.include?(text)
end

publication_service = read_file("src/claimsflow/publication/service.py", errors)
require_text(
  publication_service,
  "membership delta must exactly represent every inventory addition, update,",
  "publication service complete-inventory diff",
  errors
)
require_text(
  publication_service,
  "may not reuse untrusted candidate result versions",
  "publication service failed-candidate isolation",
  errors
)

publication_adapter = read_file("src/claimsflow/adapters/bigquery_publication.py", errors)
{
  "publication_candidate_inventory" => "persisted candidate inventory",
  "publication_reservation_locks" => "serialized publication-ID reservation",
  "ASSERT @@row_count = 1" => "row-updated compare-and-swap proof",
  "IS DISTINCT FROM 'passed'" => "fail-closed gate status",
  "membership does not exactly match its complete inventory" => "independent inventory gate"
}.each do |text, label|
  errors << "BigQuery publication adapter must declare #{label}" unless publication_adapter.include?(text)
end

quality_docs = read_file("docs/development/data-quality-quarantine.md", errors)
%w[accepted accepted_with_warning quarantined rejected duplicate_no_op].each do |disposition|
  require_text(quality_docs, disposition, "data-quality guide", errors)
end
require_text(quality_docs, "fail-closed publication", "data-quality guide", errors)
require_text(quality_docs, "without overwriting raw evidence", "data-quality guide", errors)
require_text(quality_docs, "durable SQLite", "data-quality guide", errors)
require_text(quality_docs, "implementation hashes", "data-quality guide", errors)
require_text(quality_docs, "hourly evaluation window", "data-quality guide", errors)
require_text(quality_docs, "131 source-identity/rule pairs", "data-quality guide", errors)

quality_service = read_file("src/claimsflow/quality/service.py", errors)
require_text(quality_service, "deterministic semantic reconstruction", "quality service", errors)
require_text(quality_service, "configuration_sha256", "quality service", errors)
require_text(quality_service, "_reject_existing_symlink_components", "quality service", errors)
quality_registry = read_file("src/claimsflow/adapters/local_registry.py", errors)
require_text(quality_registry, "CREATE TABLE IF NOT EXISTS quality_runs", "quality registry", errors)

inventory = read_file("docs/development/component-inventory.md", errors)
["Python", "dbt", "Airflow", "Terraform", "GitHub Actions"].each do |component|
  require_text(inventory, component, "component inventory", errors)
end
require_text(inventory, "Deferred", "component inventory", errors)
require_text(inventory, "Phase 4B.2", "component inventory", errors)
require_text(inventory, "Phase 4B.3", "component inventory", errors)

readme = read_file("README.md", errors)
require_text(readme, "Phase 1", "README", errors)
require_text(readme, "Phase 4B.2", "README", errors)
require_text(readme, "docs/development/README.md", "README", errors)

new_roots = %w[
  .github/workflows/project-foundation.yml
  .dockerignore
  .env.example
  .gitignore
  .python-version
  Makefile
  README.md
  analytics/dbt
  compose.yaml
  config
  docs/development
  infra/terraform
  orchestration/airflow
  pyproject.toml
  scripts/validate_project_scaffolding.rb
  scripts/test_project_scaffolding_validator.rb
  src
  tests
]
governed_files = new_roots.flat_map do |entry|
  path = File.join(ROOT, entry)
  File.directory?(path) ? Dir.glob(File.join(path, "**", "*")) : [path]
end.select do |path|
  components = relative(path).split(File::SEPARATOR)
  File.file?(path) && (components & GENERATED_PATH_COMPONENTS).empty?
end.uniq

governed_files.each do |path|
  content = File.read(path)
  errors << "#{relative(path)} must end with a newline" unless content.end_with?("\n")
  content.lines.each_with_index do |line, index|
    errors << "#{relative(path)}:#{index + 1} has trailing whitespace" if line.match?(/[ \t]+(?:\n|\z)/)
  end
  if content.match?(/-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/)
    errors << "#{relative(path)} contains private key material"
  end
  if content.match?(/"private_key"\s*:\s*"(?!replace|example|unset)[^\"]{20,}"/i)
    errors << "#{relative(path)} contains a private key-like JSON value"
  end
end

if errors.empty?
  puts "Project scaffold validation passed (#{REQUIRED_FILES.length} required files, #{governed_files.length} governed files)."
  exit 0
end

warn "Project scaffold validation failed with #{errors.uniq.length} error(s):"
errors.uniq.each { |error| warn "- #{error}" }
exit 1
