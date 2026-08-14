locals {
  component_inventory = {
    environment    = "local"
    data_boundary  = "synthetic-only"
    production_use = "prohibited"
  }
}

resource "terraform_data" "claimsflow_local_boundary" {
  input = local.component_inventory

  lifecycle {
    prevent_destroy = true
  }
}
