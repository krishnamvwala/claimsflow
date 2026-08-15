# Local environment

The local root records the synthetic-only environment boundary without creating cloud
resources or requiring Google credentials. It exists so every supported environment has a
versioned, independently valid Terraform root.

Run `terraform init -backend=false` and `terraform validate` here. The `prevent_destroy`
guard makes accidental teardown of even this metadata an explicit reviewed change.
