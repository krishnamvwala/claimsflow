#!/usr/bin/env ruby
# frozen_string_literal: true

require "set"
require "yaml"

ROOT = File.expand_path("..", __dir__)
CONTRACT_DIR = File.join(ROOT, "contracts", "source-data")
EXPECTED = {
  "appeals.yml" => "appeals",
  "claim-lines.yml" => "claim-lines",
  "claims.yml" => "claims",
  "denials.yml" => "denials",
  "eligibility.yml" => "eligibility",
  "payments.yml" => "payments",
  "reference-data.yml" => "reference-data",
  "remittances.yml" => "remittances"
}.freeze
REQUIRED_TOP_LEVEL = %w[
  contract_version contract_id name status source_family grain description
  requirements synthetic_only fixture_profile owners delivery keys relationships
  validation_rules reconciliation freshness
].freeze
REQUIRED_DELIVERY = %w[
  format encoding delimiter header compression schedule expected_by_utc late_after mode file_pattern
].freeze
REQUIRED_FIELD = %w[name type required nullable description].freeze
REQUIRED_RULE = %w[id severity disposition condition].freeze
ENVELOPE_FIELDS = Set.new(%w[
  batch_id source_system source_file_name source_file_checksum_sha256 source_row_number
  source_record_id source_extract_at ingested_at contract_id contract_version
  raw_payload_hash_sha256 processing_status
]).freeze
ALLOWED_TYPES = Set.new(%w[
  STRING INTEGER NUMERIC(18,2) NUMERIC(9,4) DATE TIMESTAMP BOOLEAN STRING_LIST
]).freeze
ALLOWED_RULE_PAIRS = Set.new([
  %w[warning accepted_with_warning],
  %w[error quarantined],
  %w[critical rejected],
  %w[critical block_batch]
]).freeze

errors = []
contract_ids = Set.new
source_families = Set.new
rule_ids = Set.new

def require_keys(hash, keys, context, errors)
  unless hash.is_a?(Hash)
    errors << "#{context} must be a mapping"
    return
  end

  missing = keys.reject { |key| hash.key?(key) }
  errors << "#{context} missing keys: #{missing.join(', ')}" unless missing.empty?
end

def validate_schema(schema, context, errors)
  unless schema.is_a?(Array) && !schema.empty?
    errors << "#{context} schema must be a non-empty list"
    return Set.new
  end

  names = Set.new
  schema.each_with_index do |field, index|
    field_context = "#{context} field #{index + 1}"
    require_keys(field, REQUIRED_FIELD, field_context, errors)
    next unless field.is_a?(Hash)

    name = field["name"]
    errors << "#{field_context} has an invalid name" unless name.is_a?(String) && name.match?(/\A[a-z][a-z0-9_]*\z/)
    errors << "#{context} duplicates field #{name}" if names.include?(name)
    names << name if name
    errors << "#{field_context} has unsupported type #{field['type']}" unless ALLOWED_TYPES.include?(field["type"])
    errors << "#{field_context} required must be boolean" unless [true, false].include?(field["required"])
    errors << "#{field_context} nullable must be boolean" unless [true, false].include?(field["nullable"])
    errors << "#{field_context} description must be non-empty" unless field["description"].is_a?(String) && !field["description"].strip.empty?
  end
  names
end

requirements_text = File.read(File.join(ROOT, "docs", "requirements.md"))
known_requirements = requirements_text.scan(/\*\*((?:FR|NFR)-[A-Z]+-[0-9]{3}):\*\*/).flatten.to_set

actual_files = Dir.glob(File.join(CONTRACT_DIR, "*.yml")).map { |path| File.basename(path) }.sort
errors << "Expected exactly #{EXPECTED.keys.sort.join(', ')}; found #{actual_files.join(', ')}" unless actual_files == EXPECTED.keys.sort

contracts = []
EXPECTED.each do |file_name, expected_family|
  path = File.join(CONTRACT_DIR, file_name)
  next unless File.file?(path)

  begin
    contract = YAML.safe_load(File.read(path), aliases: false)
  rescue Psych::SyntaxError => e
    errors << "#{file_name} YAML syntax error: #{e.message.lines.first.strip}"
    next
  end

  context = file_name
  require_keys(contract, REQUIRED_TOP_LEVEL, context, errors)
  next unless contract.is_a?(Hash)

  contracts << contract
  contract_id = contract["contract_id"]
  family = contract["source_family"]
  errors << "#{context} contract_id must match SRC-XXX-999" unless contract_id.is_a?(String) && contract_id.match?(/\ASRC-[A-Z]{3}-[0-9]{3}\z/)
  errors << "#{context} duplicates contract_id #{contract_id}" if contract_ids.include?(contract_id)
  contract_ids << contract_id if contract_id
  errors << "#{context} source_family must be #{expected_family}" unless family == expected_family
  errors << "#{context} duplicates source_family #{family}" if source_families.include?(family)
  source_families << family if family
  errors << "#{context} contract_version must use semantic versioning" unless contract["contract_version"].to_s.match?(/\A[0-9]+\.[0-9]+\.[0-9]+\z/)
  errors << "#{context} must set synthetic_only to true" unless contract["synthetic_only"] == true

  referenced_requirements = contract["requirements"]
  unless referenced_requirements.is_a?(Array) && !referenced_requirements.empty?
    errors << "#{context} requirements must be a non-empty list"
  else
    referenced_requirements.each do |requirement_id|
      errors << "#{context} references unknown requirement #{requirement_id}" unless known_requirements.include?(requirement_id)
    end
    errors << "#{context} repeats a requirement ID" unless referenced_requirements.uniq.length == referenced_requirements.length
  end

  require_keys(contract["owners"], %w[business technical], "#{context} owners", errors)
  require_keys(contract["delivery"], REQUIRED_DELIVERY, "#{context} delivery", errors)
  fixture = contract["fixture_profile"]
  require_keys(fixture, %w[baseline_rows_per_month invalid_fixture_rate required_scenarios], "#{context} fixture_profile", errors)
  if fixture.is_a?(Hash)
    errors << "#{context} baseline_rows_per_month must be positive" unless fixture["baseline_rows_per_month"].is_a?(Integer) && fixture["baseline_rows_per_month"].positive?
    rate = fixture["invalid_fixture_rate"]
    errors << "#{context} invalid_fixture_rate must be between 0 and 1" unless rate.is_a?(Numeric) && rate.positive? && rate < 1
    scenarios = fixture["required_scenarios"]
    errors << "#{context} required_scenarios must be a non-empty unique list" unless scenarios.is_a?(Array) && !scenarios.empty? && scenarios.uniq.length == scenarios.length
  end

  field_refs = Set.new
  if contract["datasets"]
    datasets = contract["datasets"]
    unless datasets.is_a?(Array) && !datasets.empty?
      errors << "#{context} datasets must be a non-empty list"
    else
      dataset_names = Set.new
      datasets.each_with_index do |dataset, index|
        dataset_context = "#{context} dataset #{index + 1}"
        require_keys(dataset, %w[name grain natural_key source_record_id schema], dataset_context, errors)
        next unless dataset.is_a?(Hash)

        dataset_name = dataset["name"]
        errors << "#{context} duplicates dataset #{dataset_name}" if dataset_names.include?(dataset_name)
        dataset_names << dataset_name if dataset_name
        names = validate_schema(dataset["schema"], "#{context}.#{dataset_name}", errors)
        names.each { |name| field_refs << "#{dataset_name}.#{name}" }
        %w[natural_key source_record_id].each do |key_type|
          declared = dataset[key_type]
          unless declared.is_a?(Array) && !declared.empty?
            errors << "#{dataset_context} #{key_type} must be a non-empty list"
            next
          end
          declared.each do |field|
            errors << "#{dataset_context} #{key_type} field #{field} is not in schema or lineage envelope" unless names.include?(field) || ENVELOPE_FIELDS.include?(field)
          end
        end
      end
      expected_datasets = Set.new(%w[payers plans providers facilities diagnoses procedures denial-reasons])
      errors << "#{context} reference datasets must be exactly #{expected_datasets.to_a.sort.join(', ')}" unless dataset_names == expected_datasets
    end
    errors << "#{context} top-level keys must be dataset_specific" unless contract.dig("keys", "natural_key") == "dataset_specific" && contract.dig("keys", "source_record_id") == "dataset_specific"
  else
    errors << "#{context} must declare schema or datasets" unless contract.key?("schema")
    names = validate_schema(contract["schema"], context, errors)
    field_refs.merge(names)
    %w[natural_key source_record_id].each do |key_type|
      declared = contract.dig("keys", key_type)
      unless declared.is_a?(Array) && !declared.empty?
        errors << "#{context} #{key_type} must be a non-empty list"
        next
      end
      declared.each do |field|
        errors << "#{context} #{key_type} field #{field} is not in schema or lineage envelope" unless names.include?(field) || ENVELOPE_FIELDS.include?(field)
      end
    end
  end

  relationships = contract["relationships"]
  unless relationships.is_a?(Array)
    errors << "#{context} relationships must be a list"
  else
    relationships.each_with_index do |relationship, index|
      relationship_context = "#{context} relationship #{index + 1}"
      require_keys(relationship, %w[fields target required], relationship_context, errors)
      next unless relationship.is_a?(Hash)

      fields = relationship["fields"]
      errors << "#{relationship_context} fields must be a non-empty list" unless fields.is_a?(Array) && !fields.empty?
      if fields.is_a?(Array)
        fields.each do |field|
          errors << "#{relationship_context} source field #{field} is not declared" unless field_refs.include?(field) || field_refs.include?(field.to_s.split(".").last)
        end
      end
      target_family = relationship["target"].to_s.split(".").first
      errors << "#{relationship_context} targets unknown source family #{target_family}" unless EXPECTED.value?(target_family)
      errors << "#{relationship_context} required must be boolean" unless [true, false].include?(relationship["required"])
    end
  end

  rules = contract["validation_rules"]
  unless rules.is_a?(Array) && !rules.empty?
    errors << "#{context} validation_rules must be a non-empty list"
  else
    rules.each_with_index do |rule, index|
      rule_context = "#{context} rule #{index + 1}"
      require_keys(rule, REQUIRED_RULE, rule_context, errors)
      next unless rule.is_a?(Hash)

      rule_id = rule["id"]
      errors << "#{rule_context} has invalid rule ID #{rule_id}" unless rule_id.is_a?(String) && rule_id.match?(/\ADQ-[A-Z]{3}-[0-9]{3}\z/)
      errors << "Duplicate validation rule ID #{rule_id}" if rule_ids.include?(rule_id)
      rule_ids << rule_id if rule_id
      pair = [rule["severity"], rule["disposition"]]
      errors << "#{rule_context} has invalid severity/disposition #{pair.join('/')}" unless ALLOWED_RULE_PAIRS.include?(pair)
      errors << "#{rule_context} condition must be non-empty" unless rule["condition"].is_a?(String) && !rule["condition"].strip.empty?
    end
  end

  require_keys(contract["reconciliation"], %w[record_count tolerance_usd], "#{context} reconciliation", errors)
  reconciliation_amounts = contract.dig("reconciliation", "amounts")
  if reconciliation_amounts
    unless reconciliation_amounts.is_a?(Array) && !reconciliation_amounts.empty?
      errors << "#{context} reconciliation amounts must be a non-empty list when declared"
    else
      reconciliation_amounts.each do |field|
        errors << "#{context} reconciliation amount #{field} is not declared" unless field_refs.include?(field) || field_refs.any? { |ref| ref.end_with?(".#{field}") }
      end
    end
  end
  require_keys(contract["freshness"], %w[event_field maximum_source_age], "#{context} freshness", errors)
  freshness_field = contract.dig("freshness", "event_field")
  unless ENVELOPE_FIELDS.include?(freshness_field) || field_refs.include?(freshness_field) || field_refs.any? { |field| field.end_with?(".#{freshness_field}") }
    errors << "#{context} freshness event_field #{freshness_field} is not declared"
  end
end

unless contracts.length == 8 && contract_ids.length == 8 && source_families.length == 8
  errors << "Expected 8 parsed contracts, unique IDs, and unique source families; got #{contracts.length}/#{contract_ids.length}/#{source_families.length}"
end

target_catalog = {}
contracts.each do |contract|
  family = contract["source_family"]
  if contract["datasets"]
    target_catalog[family] = contract["datasets"].to_h do |dataset|
      [dataset["name"], Set.new(dataset["schema"].map { |field| field["name"] })]
    end
  else
    target_catalog[family] = Set.new(contract["schema"].map { |field| field["name"] })
  end
end

contracts.each do |contract|
  contract["relationships"].each do |relationship|
    target = relationship["target"].to_s
    parts = target.split(".")
    family = parts.shift
    if family == "reference-data"
      dataset = parts.shift
      field_expression = parts.join(".")
      fields = target_catalog.dig(family, dataset)
      if fields.nil?
        errors << "#{contract['source_family']} relationship #{target} names an unknown reference dataset"
      elsif !fields.include?(field_expression)
        errors << "#{contract['source_family']} relationship #{target} names an unknown target field"
      end
    else
      fields = target_catalog[family]
      target_fields = parts.join(".").split("+")
      if !fields.is_a?(Set)
        errors << "#{contract['source_family']} relationship #{target} has no target schema"
      elsif target_fields.empty? || target_fields.any? { |field| !fields.include?(field) }
        errors << "#{contract['source_family']} relationship #{target} names an unknown target field"
      end
    end
  end
end

documentation_paths = [
  File.join(ROOT, "README.md"),
  File.join(ROOT, "docs", "acceptance-criteria.md"),
  File.join(ROOT, "docs", "source-data-contracts", "README.md"),
  File.join(ROOT, "docs", "source-data-contracts", "validation-policy.md"),
  File.join(ROOT, "docs", "source-data-contracts", "examples.md")
]
documentation_paths.each do |document_path|
  File.read(document_path).scan(/\[[^\]]+\]\(([^)]+)\)/).flatten.each do |link|
    next if link.start_with?("http://", "https://", "#")

    link_path = link.split("#", 2).first
    resolved = File.expand_path(link_path, File.dirname(document_path))
    errors << "#{document_path.delete_prefix(ROOT + '/')} has broken link #{link}" unless File.exist?(resolved)
  end
end

if errors.empty?
  puts "Source contracts valid: 8 contracts, #{rule_ids.length} unique validation rules, #{known_requirements.length} known requirement IDs"
  exit 0
end

warn "Source contract validation failed with #{errors.length} issue(s):"
errors.each { |error| warn "- #{error}" }
exit 1
