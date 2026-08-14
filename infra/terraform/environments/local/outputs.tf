output "component_inventory" {
  description = "Non-secret local environment boundary metadata."
  value       = terraform_data.claimsflow_local_boundary.output
}
