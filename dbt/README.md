# dbt

**Owner:** Dev 1 (framework); Dev 4 (Dockerfile, entrypoint.sh)  
**Tasks:** 0.4, C1, E3

dbt project. Build locally with `--target local` (datasets `dbt_<you>_*`), never into build_dev or wh_dev.

**Rule for working in parallel:** one `.sql` and one `.yml` per model, named after the model. Do not put several models in a shared `schema.yml`; that is where merge conflicts come from.

## Files to create here

| File | Task | Owner | Day | Notes |
| --- | --- | --- | --- | --- |
| `dbt_project.yml, profiles.yml, packages.yml, requirements.txt` | 0.4 | Dev 1 | 1-2 | Targets local, ci, dev, int |
| `Dockerfile, entrypoint.sh` | E3 | Dev 4 | 5-6 | Commands: microbatch, fullload, dbt <args> |

See `GKS-POC-Phase2-detailed-plan.md` for each task's "done when".
