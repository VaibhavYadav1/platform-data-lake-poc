# orchestration

**Owner:** Dev 4 (night-off / morning-on: Dev 2)  
**Tasks:** E4, E6, E7, E8

Workflow definitions. Reuse the `log_step` pattern from `workflow-data-lake-poc/workflow.yaml`.

## Files to create here

| File | Task | Owner | Day | Notes |
| --- | --- | --- | --- | --- |
| `micro_batch.workflow.yaml` | E4 | Dev 4 | 7-8 | Every 15 min dev, hourly int |
| `full_load.workflow.yaml` | E6 | Dev 4 | 9 | Daily, DQ39 drift check |
| `watchdog.workflow.yaml` | E7 | Dev 4 | 7-9 | Every 5 min |
| `night_off.workflow.yaml, morning_on.workflow.yaml` | E8 | Dev 2 | 5-6 |  |

See `GKS-POC-Phase2-detailed-plan.md` for each task's "done when".
