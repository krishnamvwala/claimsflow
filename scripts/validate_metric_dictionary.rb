#!/usr/bin/env ruby
# frozen_string_literal: true

require "set"
require "yaml"

ROOT = File.expand_path("..", __dir__)
METRIC_DIR = File.join(ROOT, "contracts", "metrics")
EXPECTED = {
  "appeal-success-rate.yml" => ["appeal_success_rate", "MET-APS-001", "APS"],
  "clean-claim-rate.yml" => ["clean_claim_rate", "MET-CLN-001", "CLN"],
  "days-in-ar.yml" => ["days_in_accounts_receivable", "MET-DAR-001", "DAR"],
  "denial-rate.yml" => ["denial_rate", "MET-DEN-001", "DEN"],
  "first-pass-acceptance-rate.yml" => ["first_pass_acceptance_rate", "MET-FPA-001", "FPA"],
  "net-collection-rate.yml" => ["net_collection_rate", "MET-NCR-001", "NCR"],
  "outstanding-balance.yml" => ["outstanding_balance", "MET-ARB-001", "ARB"],
  "recovered-revenue.yml" => ["recovered_revenue", "MET-REV-001", "REV"]
}.freeze
REQUIRED_SEMANTIC_REFERENCES = {
  "denial_rate" => {
    "numerator" => %w[claims.source_system claims.claim_id claims.submission_sequence denials.claim_source_system denials.claim_id denials.claim_submission_sequence],
    "denominator" => %w[claims.source_system claims.claim_id claims.submission_sequence claims.adjudicated_at claims.claim_status]
  },
  "clean_claim_rate" => {
    "numerator" => %w[claims.source_system claims.claim_id claims.submission_sequence claims.original_claim_source_system claims.original_claim_id claims.original_submission_sequence claims.submission_type claims.clean_claim_flag claims.first_pass_accepted_flag claims.claim_status denials.claim_source_system denials.claim_id denials.claim_submission_sequence],
    "denominator" => %w[claims.source_system claims.claim_id claims.submission_sequence claims.submission_type claims.adjudicated_at claims.claim_status]
  },
  "first_pass_acceptance_rate" => {
    "numerator" => %w[claims.source_system claims.claim_id claims.submission_sequence claims.first_response_at claims.first_response_disposition claims.first_pass_accepted_flag],
    "denominator" => %w[claims.source_system claims.claim_id claims.submission_sequence claims.submission_type claims.first_response_at claims.first_response_disposition]
  },
  "days_in_accounts_receivable" => {
    "numerator" => %w[claims.source_system claims.claim_id claims.submission_sequence claims.outstanding_balance claims.claim_status],
    "denominator" => %w[claims.source_system claims.claim_id claims.submission_sequence claims.submitted_at claims.billed_amount claims.claim_status]
  },
  "outstanding_balance" => {
    "numerator" => %w[claims.source_system claims.claim_id claims.submission_sequence claims.outstanding_balance claims.claim_status],
    "denominator" => []
  },
  "net_collection_rate" => {
    "numerator" => %w[payments.source_system payments.payment_id payments.claim_source_system payments.claim_id payments.claim_submission_sequence payments.transaction_type payments.direction payments.amount payments.reverses_payment_source_system payments.reverses_payment_id],
    "denominator" => %w[claims.source_system claims.claim_id claims.submission_sequence claims.billed_amount payments.transaction_type payments.direction payments.amount payments.reverses_payment_source_system payments.reverses_payment_id]
  },
  "appeal_success_rate" => {
    "numerator" => %w[appeals.source_system appeals.appeal_id appeals.decision_date appeals.outcome],
    "denominator" => %w[appeals.source_system appeals.appeal_id appeals.appeal_status appeals.filed_at appeals.decision_date appeals.outcome]
  },
  "recovered_revenue" => {
    "numerator" => %w[appeals.source_system appeals.appeal_id appeals.decision_date appeals.outcome appeals.recovered_amount],
    "denominator" => []
  }
}.freeze
REQUIRED_TOP_LEVEL = %w[
  dictionary_version metric_id slug name status description requirements acceptance_criteria
  business calculation source_dependencies validation_rules test_scenarios
].freeze
REQUIRED_BUSINESS = %w[purpose decision owner steward].freeze
REQUIRED_CALCULATION = %w[
  metric_type unit output_grain formula numerator denominator record_selection time
  dimensions null_behavior reversal_behavior adjustment_behavior precision
].freeze
REQUIRED_COMPONENT = %w[label aggregation expression grain inclusions exclusions null_handling field_references].freeze
REQUIRED_TIME = %w[mode event_field timezone boundary cutoff_rule restatement_policy].freeze
REQUIRED_PRECISION = %w[storage_type display_decimal_places rounding_mode division_by_zero].freeze
REQUIRED_DIMENSION = %w[name source_field].freeze
REQUIRED_RULE = %w[id severity condition].freeze
REQUIRED_SCENARIO = %w[id category given expected].freeze
ALLOWED_COMPONENT_AGGREGATIONS = Set.new(%w[
  count_distinct sum sum_signed sum_divided_by_constant sum_minus_sum_signed none
]).freeze
ALLOWED_DIMENSIONS = Set.new(%w[
  payer provider facility procedure diagnosis denial_reason appeal_level time
]).freeze
REQUIRED_SCENARIO_CATEGORIES = Set.new(%w[boundary null reversal dimensional]).freeze
ALLOWED_SCENARIO_CATEGORIES = REQUIRED_SCENARIO_CATEGORIES | Set.new(%w[zero_denominator empty_cohort])
ENVELOPE_TYPES = {
  "batch_id" => "STRING",
  "source_system" => "STRING",
  "source_file_name" => "STRING",
  "source_file_checksum_sha256" => "STRING",
  "source_row_number" => "INTEGER",
  "source_record_id" => "STRING",
  "source_extract_at" => "TIMESTAMP",
  "ingested_at" => "TIMESTAMP",
  "trusted_published_at" => "TIMESTAMP",
  "contract_id" => "STRING",
  "contract_version" => "STRING",
  "raw_payload_hash_sha256" => "STRING",
  "processing_status" => "STRING"
}.freeze
ENVELOPE_FIELDS = ENVELOPE_TYPES.keys.to_set.freeze

errors = []
metric_ids = Set.new
slugs = Set.new
rule_ids = Set.new
scenario_ids = Set.new

def non_empty_string?(value)
  value.is_a?(String) && !value.strip.empty?
end

def require_keys(value, keys, context, errors)
  unless value.is_a?(Hash)
    errors << "#{context} must be a mapping"
    return
  end

  missing = keys.reject { |key| value.key?(key) }
  errors << "#{context} missing keys: #{missing.join(', ')}" unless missing.empty?
end

def require_non_empty_strings(value, keys, context, errors)
  return unless value.is_a?(Hash)

  keys.each do |key|
    errors << "#{context} #{key} must be a non-empty string" unless non_empty_string?(value[key])
  end
end

def reject_unknown_keys(value, allowed_keys, context, errors)
  return unless value.is_a?(Hash)

  unknown = value.keys.to_set - allowed_keys.to_set
  errors << "#{context} has unsupported keys: #{unknown.to_a.sort.join(', ')}" unless unknown.empty?
end

def validate_string_list(value, context, errors, allow_empty: false)
  valid = value.is_a?(Array) && (allow_empty || !value.empty?) && value.uniq.length == value.length
  valid &&= value.all? { |item| non_empty_string?(item) }
  errors << "#{context} must be #{allow_empty ? 'a' : 'a non-empty'} unique list of strings" unless valid
end

requirements_text = File.read(File.join(ROOT, "docs", "requirements.md"))
known_requirements = requirements_text.scan(/\*\*((?:FR|NFR)-[A-Z]+-[0-9]{3}):\*\*/).flatten.to_set

acceptance_text = File.read(File.join(ROOT, "docs", "acceptance-criteria.md"))
acceptance_pairs = acceptance_text.scan(/^\| (AC-[A-Z]+-[0-9]{3}) \| ((?:FR|NFR)-[A-Z]+-[0-9]{3}) \|/)
acceptance_by_requirement = acceptance_pairs.each_with_object({}) do |(criterion, requirement), mapping|
  mapping[requirement] = criterion
end
known_acceptance = acceptance_pairs.map(&:first).to_set

source_catalog = {}
Dir.glob(File.join(ROOT, "contracts", "source-data", "*.yml")).sort.each do |path|
  contract = YAML.safe_load(File.read(path), aliases: false)
  next unless contract.is_a?(Hash) && contract["source_family"]

  if contract["schema"].is_a?(Array)
    field_types = contract["schema"].each_with_object(ENVELOPE_TYPES.dup) do |field, types|
      types[field["name"]] = field["type"]
    end
    source_catalog[contract["source_family"]] = {
      fields: field_types.keys.to_set,
      types: field_types,
      natural_key: contract.dig("keys", "natural_key").to_a,
      version_field: "source_updated_at"
    }
  else
    field_types = contract.fetch("datasets", []).each_with_object(ENVELOPE_TYPES.dup) do |dataset, types|
      dataset.fetch("schema", []).each { |field| types["#{dataset['name']}.#{field['name']}"] = field["type"] }
    end
    source_catalog[contract["source_family"]] = {
      fields: field_types.keys.to_set,
      types: field_types,
      natural_key: [],
      version_field: "valid_from"
    }
  end
end

actual_files = Dir.glob(File.join(METRIC_DIR, "*.yml")).map { |path| File.basename(path) }.sort
errors << "Expected exactly #{EXPECTED.keys.sort.join(', ')}; found #{actual_files.join(', ')}" unless actual_files == EXPECTED.keys.sort

metric_records = []
EXPECTED.each do |file_name, (expected_slug, expected_id, prefix)|
  path = File.join(METRIC_DIR, file_name)
  next unless File.file?(path)

  begin
    metric = YAML.safe_load(File.read(path), aliases: false)
  rescue Psych::SyntaxError => e
    errors << "#{file_name} YAML syntax error: #{e.message.lines.first.strip}"
    next
  end

  context = file_name
  require_keys(metric, REQUIRED_TOP_LEVEL, context, errors)
  next unless metric.is_a?(Hash)
  reject_unknown_keys(metric, REQUIRED_TOP_LEVEL, context, errors)

  require_non_empty_strings(metric, %w[metric_id slug name status description], context, errors)
  errors << "#{context} dictionary_version must use semantic versioning" unless metric["dictionary_version"].to_s.match?(/\A[0-9]+\.[0-9]+\.[0-9]+\z/)
  errors << "#{context} slug must be #{expected_slug}" unless metric["slug"] == expected_slug
  errors << "#{context} metric_id must be #{expected_id}" unless metric["metric_id"] == expected_id
  errors << "#{context} status must be baseline_draft" unless metric["status"] == "baseline_draft"
  errors << "Duplicate metric_id #{metric['metric_id']}" if metric_ids.include?(metric["metric_id"])
  errors << "Duplicate metric slug #{metric['slug']}" if slugs.include?(metric["slug"])
  metric_ids << metric["metric_id"] if metric["metric_id"]
  slugs << metric["slug"] if metric["slug"]

  requirements = metric["requirements"]
  validate_string_list(requirements, "#{context} requirements", errors)
  requirements.to_a.each do |requirement|
    errors << "#{context} references unknown requirement #{requirement}" unless known_requirements.include?(requirement)
  end
  common_metric_requirements = %w[FR-MET-001 FR-MET-002 FR-MET-004 FR-MET-005]
  errors << "#{context} must cite #{common_metric_requirements.join(', ')}" unless common_metric_requirements.all? { |requirement| requirements.to_a.include?(requirement) }

  acceptance = metric["acceptance_criteria"]
  validate_string_list(acceptance, "#{context} acceptance_criteria", errors)
  acceptance.to_a.each do |criterion|
    errors << "#{context} references unknown acceptance criterion #{criterion}" unless known_acceptance.include?(criterion)
  end
  expected_acceptance = requirements.to_a.map { |requirement| acceptance_by_requirement[requirement] }.compact
  errors << "#{context} acceptance_criteria must exactly follow requirement mappings" unless acceptance == expected_acceptance

  business = metric["business"]
  require_keys(business, REQUIRED_BUSINESS, "#{context} business", errors)
  reject_unknown_keys(business, REQUIRED_BUSINESS, "#{context} business", errors)
  require_non_empty_strings(business, REQUIRED_BUSINESS, "#{context} business", errors)

  calculation = metric["calculation"]
  require_keys(calculation, REQUIRED_CALCULATION, "#{context} calculation", errors)
  reject_unknown_keys(calculation, REQUIRED_CALCULATION, "#{context} calculation", errors)
  if calculation.is_a?(Hash)
    require_non_empty_strings(calculation, %w[metric_type unit output_grain formula null_behavior reversal_behavior adjustment_behavior], "#{context} calculation", errors)
    metric_type = calculation["metric_type"]
    errors << "#{context} metric_type must be ratio duration or currency" unless %w[ratio duration currency].include?(metric_type)
    expected_unit = {"ratio" => "percent", "duration" => "days", "currency" => "USD"}[metric_type]
    errors << "#{context} unit must be #{expected_unit}" unless calculation["unit"] == expected_unit

    %w[numerator denominator].each do |component_name|
      component = calculation[component_name]
      component_context = "#{context} #{component_name}"
      require_keys(component, REQUIRED_COMPONENT, component_context, errors)
      reject_unknown_keys(component, REQUIRED_COMPONENT, component_context, errors)
      require_non_empty_strings(component, %w[label aggregation expression grain null_handling], component_context, errors)
      next unless component.is_a?(Hash)

      errors << "#{component_context} aggregation #{component['aggregation']} is unsupported" unless ALLOWED_COMPONENT_AGGREGATIONS.include?(component["aggregation"])

      allow_empty = component_name == "denominator" && component["aggregation"] == "none"
      validate_string_list(component["inclusions"], "#{component_context} inclusions", errors, allow_empty: allow_empty)
      validate_string_list(component["exclusions"], "#{component_context} exclusions", errors, allow_empty: true)
      validate_string_list(component["field_references"], "#{component_context} field_references", errors, allow_empty: allow_empty)
    end

    denominator = calculation["denominator"]
    if %w[ratio duration].include?(metric_type)
      errors << "#{context} ratio/duration denominator cannot be not_applicable" if denominator.is_a?(Hash) && denominator["aggregation"] == "none"
    elsif metric_type == "currency"
      errors << "#{context} additive currency denominator must explicitly be not_applicable" unless denominator.is_a?(Hash) && denominator["aggregation"] == "none" && denominator["expression"] == "not_applicable"
    end

    validate_string_list(calculation["record_selection"], "#{context} record_selection", errors)

    time = calculation["time"]
    require_keys(time, REQUIRED_TIME, "#{context} time", errors)
    reject_unknown_keys(time, REQUIRED_TIME, "#{context} time", errors)
    require_non_empty_strings(time, REQUIRED_TIME, "#{context} time", errors)
    if time.is_a?(Hash)
      errors << "#{context} time mode must be period or as_of" unless %w[period as_of].include?(time["mode"])
      errors << "#{context} time timezone must be UTC" unless time["timezone"] == "UTC"
      expected_boundary = time["mode"] == "period" ? "start_inclusive_end_exclusive" : "as_of_date_end_inclusive"
      errors << "#{context} time boundary must be #{expected_boundary}" unless time["boundary"] == expected_boundary
    end

    dimensions = calculation["dimensions"]
    if !dimensions.is_a?(Array) || dimensions.empty?
      errors << "#{context} dimensions must be a non-empty list"
      dimensions = []
    end
    dimension_names = []
    dimensions.each_with_index do |dimension, index|
      dimension_context = "#{context} dimension #{index + 1}"
      require_keys(dimension, REQUIRED_DIMENSION, dimension_context, errors)
      reject_unknown_keys(dimension, REQUIRED_DIMENSION, dimension_context, errors)
      require_non_empty_strings(dimension, REQUIRED_DIMENSION, dimension_context, errors)
      next unless dimension.is_a?(Hash)

      name = dimension["name"]
      dimension_names << name
      errors << "#{dimension_context} uses unsupported dimension #{name}" unless ALLOWED_DIMENSIONS.include?(name)
    end
    errors << "#{context} repeats a dimension name" unless dimension_names.uniq.length == dimension_names.length
    errors << "#{context} must include a time dimension" unless dimension_names.include?("time")

    precision = calculation["precision"]
    require_keys(precision, REQUIRED_PRECISION, "#{context} precision", errors)
    reject_unknown_keys(precision, REQUIRED_PRECISION, "#{context} precision", errors)
    if precision.is_a?(Hash)
      errors << "#{context} precision storage_type must be NUMERIC(18,2) or NUMERIC(18,6)" unless ["NUMERIC(18,2)", "NUMERIC(18,6)"].include?(precision["storage_type"])
      errors << "#{context} display_decimal_places must be an integer from 0 through 6" unless precision["display_decimal_places"].is_a?(Integer) && (0..6).cover?(precision["display_decimal_places"])
      errors << "#{context} rounding_mode must be half_away_from_zero" unless precision["rounding_mode"] == "half_away_from_zero"
      expected_division = metric_type == "currency" ? "not_applicable" : "null"
      errors << "#{context} division_by_zero must be #{expected_division}" unless precision["division_by_zero"] == expected_division
    end
  end

  dependencies = metric["source_dependencies"]
  if !dependencies.is_a?(Hash) || dependencies.empty?
    errors << "#{context} source_dependencies must be a non-empty mapping"
    dependencies = {}
  end
  dependencies.each do |family, fields|
    if !source_catalog.key?(family)
      errors << "#{context} references unknown source family #{family}"
      next
    end
    validate_string_list(fields, "#{context} source dependency #{family}", errors)
    required_control_fields = source_catalog[family][:natural_key] + [source_catalog[family][:version_field], "trusted_published_at", "processing_status"]
    missing_control_fields = required_control_fields.reject { |field| fields.to_a.include?(field) }
    unless missing_control_fields.empty?
      errors << "#{context} source dependency #{family} missing identity/version/knowledge fields: #{missing_control_fields.join(', ')}"
    end
    fields.to_a.each do |field|
      errors << "#{context} source dependency #{family}.#{field} is not declared" unless source_catalog[family][:fields].include?(field)
    end
  end

  calculation.to_h.values_at("numerator", "denominator").compact.each do |component|
    component.to_h.fetch("field_references", []).each do |reference|
      family, field = reference.split(".", 2)
      if !dependencies.key?(family) || !source_catalog.key?(family) || !source_catalog[family][:fields].include?(field)
        errors << "#{context} component field reference #{reference} is not declared"
      elsif !dependencies[family].to_a.include?(field)
        errors << "#{context} component field reference #{reference} must appear in source_dependencies"
      end
    end
  end

  REQUIRED_SEMANTIC_REFERENCES.fetch(metric["slug"], {}).each do |component_name, required_references|
    actual_references = calculation.to_h.dig(component_name, "field_references").to_a
    missing_references = required_references.reject { |reference| actual_references.include?(reference) }
    unless missing_references.empty?
      errors << "#{context} #{component_name} missing required semantic field references: #{missing_references.join(', ')}"
    end
  end

  calculation.to_h.fetch("dimensions", []).each do |dimension|
    next unless dimension.is_a?(Hash) && non_empty_string?(dimension["source_field"])

    family, field = dimension["source_field"].split(".", 2)
    unless dependencies[family].to_a.include?(field)
      errors << "#{context} dimension source #{dimension['source_field']} must appear in source_dependencies"
    end
    if dimension["name"] == "procedure" && !dependencies[family].to_a.include?("procedure_code_system")
      errors << "#{context} procedure dimension must declare procedure_code_system companion dependency"
    elsif dimension["name"] == "diagnosis"
      expected_system_field = field == "primary_diagnosis_code" ? "primary_diagnosis_code_system" : "diagnosis_code_system"
      unless dependencies[family].to_a.include?(expected_system_field)
        errors << "#{context} diagnosis dimension must declare #{expected_system_field} companion dependency"
      end
    end
  end

  time_event_field = calculation.to_h.dig("time", "event_field")
  if non_empty_string?(time_event_field)
    time_family, time_field = time_event_field.split(".", 2)
    unless dependencies[time_family].to_a.include?(time_field)
      errors << "#{context} time event_field #{time_event_field} must appear in source_dependencies"
    end
    time_type = source_catalog.dig(time_family, :types, time_field)
    errors << "#{context} time event_field #{time_event_field} must have DATE or TIMESTAMP type" unless %w[DATE TIMESTAMP].include?(time_type)
  end

  if metric["slug"] == "first_pass_acceptance_rate"
    required_first_response_fields = %w[first_response_at first_response_disposition first_pass_accepted_flag]
    missing_first_response_fields = required_first_response_fields.reject { |field| dependencies["claims"].to_a.include?(field) }
    errors << "#{context} must derive first-pass acceptance from governed first-response fields" unless missing_first_response_fields.empty?
  end

  if metric["slug"] == "denial_rate"
    dimension_names = calculation.to_h.fetch("dimensions", []).map { |dimension| dimension["name"] }
    errors << "#{context} must not expose denial_reason as an undefined denominator dimension" if dimension_names.include?("denial_reason")
  end

  line_attribution_dimensions = calculation.to_h.fetch("dimensions", []).select do |dimension|
    %w[procedure diagnosis].include?(dimension["name"]) && dimension["source_field"].to_s.start_with?("claim-lines.")
  end
  if dependencies.key?("denials") && !line_attribution_dimensions.empty?
    required_denial_line_fields = %w[claim_source_system claim_id claim_submission_sequence claim_line_number claim_line_id]
    missing_denial_line_fields = required_denial_line_fields.reject { |field| dependencies["denials"].to_a.include?(field) }
    errors << "#{context} procedure/diagnosis attribution requires complete denial line pointers" unless missing_denial_line_fields.empty?
  end

  rules = metric["validation_rules"]
  if !rules.is_a?(Array) || rules.length < 4
    errors << "#{context} validation_rules must contain at least four rules"
    rules = []
  end
  rules.each_with_index do |rule, index|
    rule_context = "#{context} validation rule #{index + 1}"
    require_keys(rule, REQUIRED_RULE, rule_context, errors)
    reject_unknown_keys(rule, REQUIRED_RULE, rule_context, errors)
    require_non_empty_strings(rule, REQUIRED_RULE, rule_context, errors)
    next unless rule.is_a?(Hash)

    rule_id = rule["id"]
    errors << "#{rule_context} id must match MQ-#{prefix}-999" unless rule_id.to_s.match?(/\AMQ-#{prefix}-[0-9]{3}\z/)
    errors << "Duplicate metric validation rule #{rule_id}" if rule_ids.include?(rule_id)
    rule_ids << rule_id if rule_id
    errors << "#{rule_context} severity must be warning error or critical" unless %w[warning error critical].include?(rule["severity"])
  end

  scenarios = metric["test_scenarios"]
  if !scenarios.is_a?(Array) || scenarios.length < 5
    errors << "#{context} test_scenarios must contain at least five cases"
    scenarios = []
  end
  categories = Set.new
  scenarios.each_with_index do |scenario, index|
    scenario_context = "#{context} test scenario #{index + 1}"
    require_keys(scenario, REQUIRED_SCENARIO, scenario_context, errors)
    reject_unknown_keys(scenario, REQUIRED_SCENARIO, scenario_context, errors)
    require_non_empty_strings(scenario, REQUIRED_SCENARIO, scenario_context, errors)
    next unless scenario.is_a?(Hash)

    scenario_id = scenario["id"]
    errors << "#{scenario_context} id must match MT-#{prefix}-999" unless scenario_id.to_s.match?(/\AMT-#{prefix}-[0-9]{3}\z/)
    errors << "Duplicate metric test scenario #{scenario_id}" if scenario_ids.include?(scenario_id)
    scenario_ids << scenario_id if scenario_id
    categories << scenario["category"]
    errors << "#{scenario_context} category #{scenario['category']} is unsupported" unless ALLOWED_SCENARIO_CATEGORIES.include?(scenario["category"])
  end
  errors << "#{context} scenarios must cover boundary null reversal and dimensional behavior" unless REQUIRED_SCENARIO_CATEGORIES.subset?(categories)
  required_terminal_category = calculation.to_h["metric_type"] == "currency" ? "empty_cohort" : "zero_denominator"
  errors << "#{context} scenarios must cover #{required_terminal_category}" unless categories.include?(required_terminal_category)

  metric_records << metric
end

errors << "Expected 8 unique metric IDs and slugs" unless metric_records.length == 8 && metric_ids.length == 8 && slugs.length == 8

required_denial_dimensions = Set.new(%w[payer provider facility procedure diagnosis denial_reason time])
denial_dimensions = metric_records.select { |metric| metric["requirements"].to_a.include?("FR-MET-003") }.flat_map do |metric|
  metric.dig("calculation", "dimensions").to_a.map { |dimension| dimension["name"] }
end.to_set
errors << "Metric dictionary must collectively support every FR-MET-003 denial-analysis dimension" unless required_denial_dimensions.subset?(denial_dimensions)

documentation_paths = [
  File.join(ROOT, "README.md"),
  File.join(ROOT, "docs", "requirements.md"),
  File.join(ROOT, "docs", "acceptance-criteria.md"),
  File.join(ROOT, "docs", "metric-dictionary", "README.md"),
  File.join(ROOT, "docs", "metric-dictionary", "examples.md")
]
documentation_paths.each do |document_path|
  unless File.file?(document_path)
    errors << "Missing required documentation #{document_path.delete_prefix(ROOT + '/')}"
    next
  end

  File.read(document_path).scan(/\[[^\]]+\]\(([^)]+)\)/).flatten.each do |link|
    next if link.start_with?("http://", "https://", "#")

    resolved = File.expand_path(link.split("#", 2).first, File.dirname(document_path))
    errors << "#{document_path.delete_prefix(ROOT + '/')} has broken link #{link}" unless File.exist?(resolved)
  end
end

dictionary_readme_path = File.join(ROOT, "docs", "metric-dictionary", "README.md")
if File.file?(dictionary_readme_path)
  dictionary_readme = File.read(dictionary_readme_path)
  EXPECTED.each_key do |file_name|
    errors << "Metric dictionary README must link #{file_name}" unless dictionary_readme.include?("../../contracts/metrics/#{file_name}")
  end
end

if errors.empty?
  puts "Metric dictionary valid: 8 metrics, #{rule_ids.length} unique validation rules, #{scenario_ids.length} required scenarios"
  exit 0
end

warn "Metric dictionary validation failed with #{errors.length} issue(s):"
errors.each { |error| warn "- #{error}" }
exit 1
