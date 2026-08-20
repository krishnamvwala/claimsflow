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
  analytics/dbt/models/staging/_sources.yml
  analytics/dbt/models/staging/_staging.yml
  analytics/dbt/models/staging/README.md
  analytics/dbt/models/staging/stg_validated_records.sql
  analytics/dbt/models/intermediate/README.md
  analytics/dbt/models/curated/README.md
  analytics/dbt/models/semantic/README.md
  analytics/dbt/models/operational/README.md
  analytics/dbt/tests/staging_publication_scope.sql
  analytics/dbt/tests/staging_reconciles_to_quality_counts.sql
  analytics/dbt/tests/staging_reconciles_to_typed_models.sql
  analytics/dbt/tests/staging_reconciles_to_validated_record_set.sql
  analytics/dbt/tests/staging_requires_every_validation.sql
  compose.yaml
  config/dbt/profiles.yml
  config/data-quality-policy.yml
  config/release-manifest.example.json
  config/release-manifest.schema.json
  docs/development/README.md
  docs/development/data-quality-quarantine.md
  docs/development/dbt-validated-staging.md
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
  src/claimsflow/cli.py
  src/claimsflow/config.py
  src/claimsflow/domain/quality.py
  src/claimsflow/logging_config.py
  src/claimsflow/quality/__init__.py
  src/claimsflow/quality/catalog.py
  src/claimsflow/quality/engine.py
  src/claimsflow/quality/service.py
  tests/unit/test_cli.py
  tests/unit/test_config.py
  tests/unit/test_dbt_staging_contract.py
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
require_text(dbt_project, "+tags: [validated_staging, phase4a]", "dbt_project.yml", errors)
require_text(dbt_project, "publication_scoped: true", "dbt_project.yml", errors)

dbt_readme = read_file("analytics/dbt/README.md", errors)
require_text(dbt_readme, "Phase 4A implements the validated staging boundary", "dbt README", errors)
require_text(dbt_readme, "validation-selection fingerprint", "dbt README", errors)
reject_text(dbt_project, "raw_source", "dbt_project.yml", errors)
if dbt_project.match?(/curated:\s*\n\s+\+materialized:\s*table/)
  errors << "dbt Phase 4A publication boundary must prohibit curated table models"
end

sql_models = Dir.glob(File.join(ROOT, "analytics/dbt/models/**/*.sql"))
expected_sql_models = ["stg_validated_records", *STAGING_MODELS.values].map do |model|
  File.join(ROOT, "analytics/dbt/models/staging/#{model}.sql")
end.sort
unless sql_models.sort == expected_sql_models
  missing = expected_sql_models - sql_models
  unexpected = sql_models - expected_sql_models
  errors << "dbt Phase 4A model inventory must contain only validated staging SQL: " \
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
  "local_md5(canonical_selection)" => "deterministic candidate-selection fingerprint"
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

properties_generator = read_file("scripts/render_dbt_staging_properties.py", errors)
require_text(properties_generator, 'parser.add_argument("--check"', "dbt properties generator", errors)
require_text(properties_generator, "if set(result) != set(MODEL_NAMES)", "dbt properties generator", errors)

dbt_schema_macro = read_file("analytics/dbt/macros/generate_schema_name.sql", errors)
{
  "'staging': 'claimsflow_curated'" => "private staging physical dataset",
  "'intermediate': 'claimsflow_curated'" => "private intermediate physical dataset",
  "'curated': 'claimsflow_curated'" => "curated physical dataset",
  "'semantic': 'claimsflow_semantic'" => "semantic physical dataset",
  "'operational': 'claimsflow_operational'" => "operational physical dataset",
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

dbt_staging_docs = read_file("docs/development/dbt-validated-staging.md", errors)
{
  "claimsflow_publication_id" => "candidate publication identifier",
  "claimsflow_validation_ids" => "immutable validation allowlist",
  "selection-fingerprint" => "candidate isolation",
  "validated_record_set_sha256" => "cryptographic record-set binding",
  "fourteen typed models" => "complete staging identity inventory",
  "accepted plus warned" => "quality count reconciliation",
  "Phase 4B" => "next milestone boundary"
}.each do |text, label|
  errors << "dbt validated-staging guide must declare #{label}" unless dbt_staging_docs.include?(text)
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

readme = read_file("README.md", errors)
require_text(readme, "Phase 1", "README", errors)
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
