# scripts/ci

**Owner:** Dev 4 (Dev 5 for the customer check)  
**Tasks:** E1, B8

Checks run by cloudbuild/pr.yaml.

## Files to create here

| File | Task | Owner | Day | Notes |
| --- | --- | --- | --- | --- |
| `check_single_definition.py` | B8 | Dev 5 | 5-6 | One definition of customer |
| `check_env_diff.py` | E1 | Dev 4 | 3-5 | Only *.tfvars / *.backend.hcl differ |
| `check_model_tests.py` | C1 | Dev 1 | 3 | Key tests + descriptions on every model |

See `GKS-POC-Phase2-detailed-plan.md` for each task's "done when".
