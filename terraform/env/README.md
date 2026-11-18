# terraform/env

**Owner:** Dev 4  
**Tasks:** 0.2, E9

One root module for both environments. The ONLY files that may differ between dev and int are `*.tfvars` and `*.backend.hcl` (checked in CI, AT-31).

## Files to create here

| File | Task | Owner | Day | Notes |
| --- | --- | --- | --- | --- |
| `main.tf, variables.tf, outputs.tf, versions.tf, providers.tf` | 0.2 | Dev 4 | 1-2 |  |
| `dev.tfvars, dev.backend.hcl` | 0.2 | Dev 4 | 1-2 |  |
| `int.tfvars, int.backend.hcl` | E9 | Dev 4 | 9-10 |  |

See `GKS-POC-Phase2-detailed-plan.md` for each task's "done when".
