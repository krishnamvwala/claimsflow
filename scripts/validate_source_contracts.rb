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
  requirements acceptance_criteria synthetic_only fixture_profile owners delivery keys
  relationships validation_rules reconciliation freshness
].freeze
REQUIRED_DELIVERY = %w[
  format encoding delimiter header compression schedule expected_by_utc late_after mode file_pattern
].freeze
REQUIRED_FIELD = %w[name type required nullable description].freeze
REQUIRED_RULE = %w[id severity disposition condition].freeze
REQUIRED_RELATIONSHIP = %w[fields target required match cardinality].freeze
ALLOWED_FIELD_KEYS = Set.new(REQUIRED_FIELD + %w[
  allowed_values pattern minimum maximum minimum_exclusive
]).freeze
ALLOWED_RELATIONSHIP_KEYS = Set.new(REQUIRED_RELATIONSHIP + %w[
  as_of_field as_of_conversion mode
]).freeze
ENVELOPE_TYPES = {
  "batch_id" => "STRING",
  "source_system" => "STRING",
  "source_file_name" => "STRING",
  "source_file_checksum_sha256" => "STRING",
  "source_row_number" => "INTEGER",
  "source_record_id" => "STRING",
  "source_extract_at" => "TIMESTAMP",
  "ingested_at" => "TIMESTAMP",
  "contract_id" => "STRING",
  "contract_version" => "STRING",
  "raw_payload_hash_sha256" => "STRING",
  "processing_status" => "STRING"
}.freeze
ENVELOPE_FIELDS = ENVELOPE_TYPES.keys.to_set.freeze
ALLOWED_TYPES = Set.new(%w[
  STRING INTEGER NUMERIC(18,2) NUMERIC(9,4) DATE TIMESTAMP BOOLEAN STRING_LIST
]).freeze
ALLOWED_RULE_PAIRS = Set.new([
  %w[warning accepted_with_warning],
  %w[error quarantined],
  %w[critical rejected],
  %w[critical block_batch]
]).freeze
EXPECTED_REFERENCE_DATASETS = Set.new(%w[
  payers plans providers facilities diagnoses procedures denial-reasons
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

def non_empty_string?(value)
  value.is_a?(String) && !value.strip.empty?
end

def require_non_empty_strings(hash, keys, context, errors)
  return unless hash.is_a?(Hash)

  keys.each do |key|
    errors << "#{context} #{key} must be a non-empty string" unless non_empty_string?(hash[key])
  end
end

def validate_schema(schema, context, errors)
  unless schema.is_a?(Array) && !schema.empty?
    errors << "#{context} schema must be a non-empty list"
    return {names: Set.new, types: {}}
  end

  names = Set.new
  types = {}
  schema.each_with_index do |field, index|
    field_context = "#{context} field #{index + 1}"
    require_keys(field, REQUIRED_FIELD, field_context, errors)
    next unless field.is_a?(Hash)

    unsupported_keys = field.keys.to_set - ALLOWED_FIELD_KEYS
    errors << "#{field_context} has unsupported schema keys: #{unsupported_keys.to_a.sort.join(', ')}" unless unsupported_keys.empty?

    name = field["name"]
    type = field["type"]
    errors << "#{field_context} has an invalid name" unless name.is_a?(String) && name.match?(/\A[a-z][a-z0-9_]*\z/)
    errors << "#{context} duplicates field #{name}" if names.include?(name)
    names << name if name
    types[name] = type if name
    errors << "#{field_context} has unsupported type #{type}" unless ALLOWED_TYPES.include?(type)
    errors << "#{field_context} required must be boolean" unless [true, false].include?(field["required"])
    errors << "#{field_context} nullable must be boolean" unless [true, false].include?(field["nullable"])
    errors << "#{field_context} description must be non-empty" unless non_empty_string?(field["description"])

    if field.key?("allowed_values")
      values = field["allowed_values"]
      valid_values = values.is_a?(Array) && !values.empty? && values.uniq.length == values.length
      valid_values &&= case type
                       when "STRING", "STRING_LIST"
                         values.all? { |value| non_empty_string?(value) }
                       when "INTEGER"
                         values.all? { |value| value.is_a?(Integer) }
                       when "NUMERIC(18,2)", "NUMERIC(9,4)"
                         values.all? { |value| value.is_a?(Numeric) }
                       when "BOOLEAN"
                         values.all? { |value| [true, false].include?(value) }
                       else
                         false
                       end
      errors << "#{field_context} allowed_values must be a non-empty unique list compatible with #{type}" unless valid_values
    end

    if field.key?("pattern")
      errors << "#{field_context} pattern is permitted only for STRING or STRING_LIST" unless %w[STRING STRING_LIST].include?(type)
      if non_empty_string?(field["pattern"])
        begin
          Regexp.new(field["pattern"])
        rescue RegexpError => e
          errors << "#{field_context} pattern is invalid: #{e.message}"
        end
      else
        errors << "#{field_context} pattern must be a non-empty string"
      end
    end

    numeric_constraints = %w[minimum maximum minimum_exclusive].select { |key| field.key?(key) }
    unless numeric_constraints.empty?
      errors << "#{field_context} numeric constraints require INTEGER or NUMERIC type" unless ["INTEGER", "NUMERIC(18,2)", "NUMERIC(9,4)"].include?(type)
      numeric_constraints.each do |key|
        errors << "#{field_context} #{key} must be numeric" unless field[key].is_a?(Numeric)
      end
      errors << "#{field_context} cannot declare both minimum and minimum_exclusive" if field.key?("minimum") && field.key?("minimum_exclusive")
      lower_key = field.key?("minimum_exclusive") ? "minimum_exclusive" : "minimum"
      if field.key?(lower_key) && field.key?("maximum") && field[lower_key].is_a?(Numeric) && field["maximum"].is_a?(Numeric)
        errors << "#{field_context} #{lower_key} must be less than maximum" unless field[lower_key] < field["maximum"]
      end
    end
  end
  {names: names, types: types}
end

def parse_target(target)
  parts = target.to_s.split(".")
  family = parts.shift
  dataset = family == "reference-data" ? parts.shift : nil
  fields = parts.join(".").split("+").reject(&:empty?)
  {family: family, dataset: dataset, fields: fields}
end

requirements_text = File.read(File.join(ROOT, "docs", "requirements.md"))
known_requirements = requirements_text.scan(/\*\*((?:FR|NFR)-[A-Z]+-[0-9]{3}):\*\*/).flatten.to_set

acceptance_text = File.read(File.join(ROOT, "docs", "acceptance-criteria.md"))
acceptance_pairs = acceptance_text.scan(/^\| (AC-[A-Z]+-[0-9]{3}) \| ((?:FR|NFR)-[A-Z]+-[0-9]{3}) \|/)
acceptance_by_requirement = {}
acceptance_pairs.each do |acceptance_id, requirement_id|
  if acceptance_by_requirement.key?(requirement_id)
    errors << "Acceptance matrix maps #{requirement_id} more than once"
  else
    acceptance_by_requirement[requirement_id] = acceptance_id
  end
end
known_acceptance = acceptance_pairs.map(&:first).to_set
unless known_requirements.length == 80 && acceptance_by_requirement.length == 80 && known_acceptance.length == 80 && acceptance_by_requirement.keys.to_set == known_requirements
  errors << "Acceptance matrix must preserve exact 80-to-80 requirement traceability"
end

actual_files = Dir.glob(File.join(CONTRACT_DIR, "*.yml")).map { |path| File.basename(path) }.sort
errors << "Expected exactly #{EXPECTED.keys.sort.join(', ')}; found #{actual_files.join(', ')}" unless actual_files == EXPECTED.keys.sort

contract_records = []
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

  require_non_empty_strings(contract, %w[name status source_family grain description], context, errors)
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
  if !referenced_requirements.is_a?(Array) || referenced_requirements.empty?
    errors << "#{context} requirements must be a non-empty list"
    referenced_requirements = []
  else
    referenced_requirements.each do |requirement_id|
      errors << "#{context} references unknown requirement #{requirement_id}" unless known_requirements.include?(requirement_id)
    end
    errors << "#{context} repeats a requirement ID" unless referenced_requirements.uniq.length == referenced_requirements.length
  end

  referenced_acceptance = contract["acceptance_criteria"]
  if !referenced_acceptance.is_a?(Array) || referenced_acceptance.empty?
    errors << "#{context} acceptance_criteria must be a non-empty list"
    referenced_acceptance = []
  else
    referenced_acceptance.each do |acceptance_id|
      errors << "#{context} references unknown acceptance criterion #{acceptance_id}" unless known_acceptance.include?(acceptance_id)
    end
    errors << "#{context} repeats an acceptance criterion" unless referenced_acceptance.uniq.length == referenced_acceptance.length
  end
  expected_acceptance = referenced_requirements.map { |requirement_id| acceptance_by_requirement[requirement_id] }.compact
  errors << "#{context} acceptance_criteria must exactly follow its requirement mappings" unless referenced_acceptance == expected_acceptance

  owners = contract["owners"]
  require_keys(owners, %w[business technical], "#{context} owners", errors)
  require_non_empty_strings(owners, %w[business technical], "#{context} owners", errors)

  delivery = contract["delivery"]
  require_keys(delivery, REQUIRED_DELIVERY, "#{context} delivery", errors)
  require_non_empty_strings(delivery, REQUIRED_DELIVERY - ["header"], "#{context} delivery", errors)
  errors << "#{context} delivery header must be true" unless delivery.is_a?(Hash) && delivery["header"] == true
  if delivery.is_a?(Hash)
    errors << "#{context} delivery format must be csv" unless delivery["format"] == "csv"
    errors << "#{context} file_pattern must include source_system and sequence" unless delivery["file_pattern"].to_s.include?("{source_system}") && delivery["file_pattern"].to_s.include?("{sequence}")
  end

  fixture = contract["fixture_profile"]
  require_keys(fixture, %w[baseline_rows_per_month invalid_fixture_rate required_scenarios], "#{context} fixture_profile", errors)
  if fixture.is_a?(Hash)
    errors << "#{context} baseline_rows_per_month must be positive" unless fixture["baseline_rows_per_month"].is_a?(Integer) && fixture["baseline_rows_per_month"].positive?
    rate = fixture["invalid_fixture_rate"]
    errors << "#{context} invalid_fixture_rate must be between 0 and 1" unless rate.is_a?(Numeric) && rate.positive? && rate < 1
    scenarios = fixture["required_scenarios"]
    errors << "#{context} required_scenarios must be a non-empty unique list of values" unless scenarios.is_a?(Array) && !scenarios.empty? && scenarios.uniq.length == scenarios.length && scenarios.all? { |value| non_empty_string?(value) }
  end

  field_refs = Set.new
  field_types = {}
  dataset_catalog = {}
  if contract["datasets"]
    datasets = contract["datasets"]
    if !datasets.is_a?(Array) || datasets.empty?
      errors << "#{context} datasets must be a non-empty list"
    else
      dataset_names = Set.new
      datasets.each_with_index do |dataset, index|
        dataset_context = "#{context} dataset #{index + 1}"
        require_keys(dataset, %w[name grain natural_key source_record_id schema], dataset_context, errors)
        next unless dataset.is_a?(Hash)

        require_non_empty_strings(dataset, %w[name grain], dataset_context, errors)
        dataset_name = dataset["name"]
        errors << "#{context} duplicates dataset #{dataset_name}" if dataset_names.include?(dataset_name)
        dataset_names << dataset_name if dataset_name
        schema_result = validate_schema(dataset["schema"], "#{context}.#{dataset_name}", errors)
        names = schema_result[:names]
        names.each do |name|
          field_refs << "#{dataset_name}.#{name}"
          field_types["#{dataset_name}.#{name}"] = schema_result[:types][name]
        end
        %w[natural_key source_record_id].each do |key_type|
          declared = dataset[key_type]
          if !declared.is_a?(Array) || declared.empty?
            errors << "#{dataset_context} #{key_type} must be a non-empty list"
            next
          end
          declared.each do |field|
            errors << "#{dataset_context} #{key_type} field #{field} is not in schema or lineage envelope" unless names.include?(field) || ENVELOPE_FIELDS.include?(field)
          end
        end
        dataset_catalog[dataset_name] = {
          fields: names | ENVELOPE_FIELDS,
          field_types: schema_result[:types].merge(ENVELOPE_TYPES),
          natural_key: dataset["natural_key"]
        }
      end
      errors << "#{context} reference datasets must be exactly #{EXPECTED_REFERENCE_DATASETS.to_a.sort.join(', ')}" unless dataset_names == EXPECTED_REFERENCE_DATASETS
    end
    errors << "#{context} top-level keys must be dataset_specific" unless contract.dig("keys", "natural_key") == "dataset_specific" && contract.dig("keys", "source_record_id") == "dataset_specific"
  else
    errors << "#{context} must declare schema or datasets" unless contract.key?("schema")
    schema_result = validate_schema(contract["schema"], context, errors)
    names = schema_result[:names]
    field_refs.merge(names)
    field_refs.merge(ENVELOPE_FIELDS)
    field_types.merge!(schema_result[:types])
    field_types.merge!(ENVELOPE_TYPES)
    %w[natural_key source_record_id].each do |key_type|
      declared = contract.dig("keys", key_type)
      if !declared.is_a?(Array) || declared.empty?
        errors << "#{context} #{key_type} must be a non-empty list"
        next
      end
      declared.each do |field|
        errors << "#{context} #{key_type} field #{field} is not in schema or lineage envelope" unless names.include?(field) || ENVELOPE_FIELDS.include?(field)
      end
    end
  end

  relationships = contract["relationships"]
  if !relationships.is_a?(Array)
    errors << "#{context} relationships must be a list"
    relationships = []
  else
    relationships.each_with_index do |relationship, index|
      relationship_context = "#{context} relationship #{index + 1}"
      require_keys(relationship, REQUIRED_RELATIONSHIP, relationship_context, errors)
      next unless relationship.is_a?(Hash)

      unsupported_keys = relationship.keys.to_set - ALLOWED_RELATIONSHIP_KEYS
      errors << "#{relationship_context} has unsupported relationship keys: #{unsupported_keys.to_a.sort.join(', ')}" unless unsupported_keys.empty?

      fields = relationship["fields"]
      if !fields.is_a?(Array) || fields.empty?
        errors << "#{relationship_context} fields must be a non-empty list"
      else
        fields.each do |field|
          errors << "#{relationship_context} source field #{field} is not declared" unless field_refs.include?(field)
        end
      end
      errors << "#{relationship_context} target must be non-empty" unless non_empty_string?(relationship["target"])
      errors << "#{relationship_context} required must be boolean" unless [true, false].include?(relationship["required"])
      errors << "#{relationship_context} match must be exact_key or effective_at" unless %w[exact_key effective_at].include?(relationship["match"])
      errors << "#{relationship_context} cardinality must be non-empty" unless non_empty_string?(relationship["cardinality"])
      as_of_field = relationship["as_of_field"]
      if relationship["match"] == "effective_at"
        errors << "#{relationship_context} effective_at requires a declared as_of_field" unless non_empty_string?(as_of_field) && field_refs.include?(as_of_field)
      elsif relationship.key?("as_of_field")
        errors << "#{relationship_context} exact_key must not declare as_of_field"
      end
      if relationship["match"] != "effective_at" && relationship.key?("as_of_conversion")
        errors << "#{relationship_context} as_of_conversion is permitted only for effective_at"
      elsif relationship.key?("as_of_conversion") && relationship["as_of_conversion"] != "utc_date"
        errors << "#{relationship_context} as_of_conversion must be utc_date when present"
      end
      if relationship.key?("mode") && relationship["mode"] != "every_list_member"
        errors << "#{relationship_context} mode must be every_list_member when present"
      end
      if relationship["mode"] == "every_list_member" && !fields.to_a.any? { |field| field_types[field] == "STRING_LIST" }
        errors << "#{relationship_context} every_list_member requires a STRING_LIST source field"
      end
    end
  end

  rules = contract["validation_rules"]
  if !rules.is_a?(Array) || rules.empty?
    errors << "#{context} validation_rules must be a non-empty list"
    rules = []
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
      errors << "#{rule_context} condition must be non-empty" unless non_empty_string?(rule["condition"])
    end
    duplicate_key_rule = rules.any? do |rule|
      rule["severity"] == "critical" && rule["disposition"] == "rejected" && rule["condition"].to_s.downcase.match?(/duplicate.*natural key/)
    end
    errors << "#{context} must reject duplicate natural keys with a critical rule" unless duplicate_key_rule
  end

  reconciliation = contract["reconciliation"]
  require_keys(reconciliation, %w[record_count tolerance_usd], "#{context} reconciliation", errors)
  require_non_empty_strings(reconciliation, %w[record_count], "#{context} reconciliation", errors)
  reconciliation_amounts = contract.dig("reconciliation", "amounts")
  if reconciliation_amounts
    if !reconciliation_amounts.is_a?(Array) || reconciliation_amounts.empty?
      errors << "#{context} reconciliation amounts must be a non-empty list when declared"
    else
      reconciliation_amounts.each do |field|
        errors << "#{context} reconciliation amount #{field} is not declared" unless field_refs.include?(field) || field_refs.any? { |ref| ref.end_with?(".#{field}") }
      end
    end
  end

  freshness = contract["freshness"]
  require_keys(freshness, %w[event_field maximum_source_age], "#{context} freshness", errors)
  require_non_empty_strings(freshness, %w[event_field maximum_source_age], "#{context} freshness", errors)
  freshness_field = contract.dig("freshness", "event_field")
  unless ENVELOPE_FIELDS.include?(freshness_field) || field_refs.include?(freshness_field) || field_refs.any? { |field| field.end_with?(".#{freshness_field}") }
    errors << "#{context} freshness event_field #{freshness_field} is not declared"
  end

  contract_records << {
    file: context,
    contract: contract,
    fields: field_refs,
    field_types: field_types,
    dataset_catalog: dataset_catalog
  }
end

unless contract_records.length == 8 && contract_ids.length == 8 && source_families.length == 8
  errors << "Expected 8 parsed contracts, unique IDs, and unique source families; got #{contract_records.length}/#{contract_ids.length}/#{source_families.length}"
end

target_catalog = {}
contract_records.each do |record|
  contract = record[:contract]
  family = contract["source_family"]
  if contract["datasets"]
    target_catalog[family] = {kind: :datasets, datasets: record[:dataset_catalog]}
  else
    target_catalog[family] = {
      kind: :contract,
      fields: record[:fields],
      field_types: record[:field_types],
      natural_key: contract.dig("keys", "natural_key")
    }
  end
end

contract_records.each do |record|
  contract = record[:contract]
  contract["relationships"].each_with_index do |relationship, index|
    context = "#{record[:file]} relationship #{index + 1}"
    parsed = parse_target(relationship["target"])
    target_entry = target_catalog[parsed[:family]]
    if target_entry.nil?
      errors << "#{context} targets unknown source family #{parsed[:family]}"
      next
    end

    if parsed[:family] == "reference-data"
      target_definition = target_entry[:datasets][parsed[:dataset]]
      if target_definition.nil?
        errors << "#{context} names unknown reference dataset #{parsed[:dataset]}"
        next
      end
    elsif parsed[:dataset]
      errors << "#{context} unexpectedly names dataset #{parsed[:dataset]}"
      next
    else
      target_definition = target_entry
    end

    unknown_target_fields = parsed[:fields].reject { |field| target_definition[:fields].include?(field) }
    errors << "#{context} names unknown target fields #{unknown_target_fields.join(', ')}" unless unknown_target_fields.empty?
    source_fields = relationship["fields"].is_a?(Array) ? relationship["fields"] : []
    errors << "#{context} source and target key lengths differ" unless source_fields.length == parsed[:fields].length

    source_fields.zip(parsed[:fields]).each do |source_field, target_field|
      source_type = record[:field_types][source_field]
      target_type = target_definition[:field_types][target_field]
      next if source_type.nil? || target_type.nil?

      compatible = source_type == target_type
      compatible ||= relationship["mode"] == "every_list_member" && source_type == "STRING_LIST" && target_type == "STRING"
      errors << "#{context} has incompatible relationship types #{source_field}:#{source_type} -> #{target_field}:#{target_type}" unless compatible
    end

    if relationship["match"] == "exact_key"
      errors << "#{context} exact_key must target the complete natural key #{target_definition[:natural_key].join('+')}" unless parsed[:fields] == target_definition[:natural_key]
      expected_cardinality = relationship["required"] ? "exactly_one" : "zero_or_one"
      errors << "#{context} exact_key cardinality must be #{expected_cardinality}" unless relationship["cardinality"] == expected_cardinality
    elsif relationship["match"] == "effective_at"
      errors << "#{context} effective_at may target only reference-data datasets" unless parsed[:family] == "reference-data"
      natural_key = target_definition[:natural_key].to_a
      business_key = natural_key.reject { |field| field == "valid_from" }
      errors << "#{context} effective_at target must have valid_from in its natural key" unless natural_key.count("valid_from") == 1
      errors << "#{context} effective_at target must declare valid_from and valid_to" unless target_definition[:fields].include?("valid_from") && target_definition[:fields].include?("valid_to")
      errors << "#{context} effective_at must target the complete business key #{business_key.join('+')}" unless parsed[:fields] == business_key
      valid_from_type = target_definition[:field_types]["valid_from"]
      valid_to_type = target_definition[:field_types]["valid_to"]
      errors << "#{context} effective interval endpoints must use the same DATE or TIMESTAMP type" unless valid_from_type == valid_to_type && %w[DATE TIMESTAMP].include?(valid_from_type)
      as_of_type = record[:field_types][relationship["as_of_field"]]
      errors << "#{context} as_of_field must be DATE or TIMESTAMP" unless %w[DATE TIMESTAMP].include?(as_of_type)
      if as_of_type == valid_from_type
        errors << "#{context} must not declare as_of_conversion when interval and as-of types match" if relationship.key?("as_of_conversion")
      elsif as_of_type == "TIMESTAMP" && valid_from_type == "DATE"
        errors << "#{context} TIMESTAMP to DATE lookup requires as_of_conversion utc_date" unless relationship["as_of_conversion"] == "utc_date"
      elsif as_of_type && valid_from_type
        errors << "#{context} cannot convert #{as_of_type} as_of_field to #{valid_from_type} interval"
      end
      expected_cardinality = if relationship["mode"] == "every_list_member"
                               relationship["required"] ? "exactly_one_per_list_member" : "zero_or_one_per_list_member"
                             else
                               relationship["required"] ? "exactly_one_effective" : "zero_or_one_effective"
                             end
      errors << "#{context} effective_at cardinality must be #{expected_cardinality}" unless relationship["cardinality"] == expected_cardinality
    end
  end
end

reference_rules = contract_records.find { |record| record[:contract]["source_family"] == "reference-data" }&.dig(:contract, "validation_rules").to_a.map { |rule| rule["id"] }.to_set
required_effective_rules = Set.new(%w[DQ-REF-003 DQ-REF-004 DQ-REF-005])
errors << "reference-data.yml must enforce valid intervals, non-overlap, and one current version" unless required_effective_rules.subset?(reference_rules)

validation_policy = File.read(File.join(ROOT, "docs", "source-data-contracts", "validation-policy.md"))
duplicate_policy = validation_policy.lines.find { |line| line.start_with?("| DQ-CMN-004 |") }.to_s
unless duplicate_policy.match?(/\| warning \| duplicate_no_op(?:\s|;|\|)/) && duplicate_policy.match?(/no (?:record processing|records processed)/i)
  errors << "validation policy DQ-CMN-004 must use warning/duplicate_no_op and terminate before record processing"
end
collision_policy = validation_policy.lines.find { |line| line.start_with?("| DQ-CMN-011 |") }.to_s
unless collision_policy.match?(/same natural key/i) && collision_policy.match?(/same.*version discriminator/i) && collision_policy.match?(/different.*payload hash/i) && collision_policy.match?(/\| critical \| block_batch(?:\s|;|\|)/)
  errors << "validation policy DQ-CMN-011 must block same-key same-version different-payload collisions"
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
  puts "Source contracts valid: 8 contracts, #{rule_ids.length} unique validation rules, 80 requirement/acceptance mappings"
  exit 0
end

warn "Source contract validation failed with #{errors.length} issue(s):"
errors.each { |error| warn "- #{error}" }
exit 1
