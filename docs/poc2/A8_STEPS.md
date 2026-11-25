# A8: simulator in the cloud, runbook

**Owners:** Dev 3 (tick code, image), Dev 4 (Terraform)  
**Needs:** A3 ✅, A4 parity snapshot ✅ (announcement not sent), A7 ⏳ (needs A6 ⏳) for the case-event part  
**Done when:** the job runs every 5 minutes for 2 hours with no failures, and every source changes (guide 10.7).  
**Design:** POC A guide 10.5 (one tick), 10.6 (cloud, with "As built" notes), runbook phase 8.

> 25 Nov 2026: the code is written and tested locally; nothing is deployed. This file is the order to deploy it in
> (steps 1–9) and the checks that prove it works (V1–V10).

## What A8 builds and why

```
Cloud Scheduler poc-simulator-tick (*/5, as sa-orchestrator, created PAUSED)
  → Cloud Run job poc-source-simulator (as sa-simulator, 240 s timeout, no retries)
      1. G2 changes, one transaction  → Cloud SQL g2.* → Datastream → raw_g2.*      (the G2 change path)
      2. case events (A7)             → poc-case-events → raw_lpos.case_event        (when CASE_TOPIC is set)
      3. wheel events (A9)            → sim_g2_datalake.wheel_event                  (not built yet)
      4. CRM export, first tick of the hour (B2) → CRM landing bucket                (when CRM_BUCKET is set)
      5. heartbeat, LAST              → g2.heartbeat → raw_g2.g2_heartbeat → poc-watchdog (E7)
```

Until A8 runs, G2 only changes when someone runs a scripted batch by hand. A8 keeps the G2 change path moving all
day, which AT-16 (latency), the watchdog (E7) and the 24-hour run (phase 12) depend on.

## What's in the code

| File | What |
| --- | --- |
| `simulator/tick.py` | One tick (guide 10.5). Imports nothing from the Phase 1 generator |
| `simulator/cli.py` | `python -m simulator tick [--rate R]`; `seed`/`batch` imports are now lazy |
| `simulator/db.py` | Error text only: in the cloud, `PG_HOST=/cloudsql/<connection name>` |
| `simulator/Dockerfile`, `.gcloudignore`, `requirements-runtime.txt` | The image: public PyPI only, code in `/app/simulator`, non-root |
| `simulator/tests/test_tick.py` | 8 tests: counts in range, rate 0, 150 ticks stay valid, failed step leaves the heartbeat stale, CRM hook timing, CLI, no `data-lake-schema` import |
| `terraform/shared/simulator.tf` | `sa-simulator` + Cloud SQL client + secret accessor, the job, `run.invoker` for `sa-orchestrator`, the scheduler (paused) |
| `terraform/shared/night_off.tf`, `modules/workflows/variables.tf` | Night-off/morning-on now pause/resume `poc-simulator-tick` (was the non-existent `poc-simulator`) |

Design problems fixed (recorded in the guide, 10.5/10.6/phase 8, section 21):

1. **Dockerfile:** `COPY . .` with build context `simulator/` left no `simulator` package in the image.
2. **Phase 1 package:** the image installed `requirements.txt` (Phase 1 registry, cross-project grant). `tick`
   doesn't need the generator, so the image uses `requirements-runtime.txt` from PyPI.
3. **Connection:** Cloud Run's Cloud SQL socket and an injected password replace the Python connector, so the
   simulator uses the same `psycopg` code locally and in the cloud.
4. **Night-off** named the wrong scheduler job, so the simulator would have kept ticking against a stopped database.
5. **`CASE_TOPIC`** was hard-coded in the job; before A7 every tick would have failed. It's now a variable, empty
   by default.

## Before you start

- Work from `platform-data-lake-poc` in Git Bash, logged in with `gcloud auth login` and
  `gcloud auth application-default login`, project `gks-datalake-poc2-dev`.
- **Morning state:** `poc-ops-db` RUNNABLE and `poc-cdc-stream` RUNNING. Otherwise the tick fails (database) or the
  checks in BigQuery see nothing (stream).

```bash
gcloud sql instances describe poc-ops-db --format="value(state,settings.activationPolicy)"   # RUNNABLE ALWAYS
gcloud datastream streams describe poc-cdc-stream --location=us-central1 --format="value(state)"   # RUNNING
```

## Step 1: Send the parity-snapshot message (A4 close)

One message to Dev 1 and Dev 3: "`raw_g2_parity` is frozen; the A3 freeze is lifted." From the first tick on, G2
changes all the time. Never touch `raw_g2_parity`.

## Step 2: Run the tests locally (optional, ~1 minute)

**Why:** the same checks I ran, on your machine, before anything reaches GCP.

```bash
docker run -d --rm --name sim-test -e POSTGRES_PASSWORD=local -p 55432:5432 postgres:16
SIM_TEST_PG="host=localhost port=55432 user=postgres password=local" \
  .venv/Scripts/python.exe -m pytest simulator/tests/test_tick.py -q        # 8 passed
docker stop sim-test
```

## Step 3: Commit, then build and push the image

**Why commit first:** the image tag is the commit hash, so you can always tell which code a tick ran.

```bash
git add simulator terraform docs
git commit -m "A8: simulator tick mode, image and Cloud Run job"
git push origin main

TAG=$(git rev-parse --short HEAD)
IMAGE=us-central1-docker.pkg.dev/gks-datalake-poc2-dev/poc/poc-source-simulator:$TAG
gcloud builds submit simulator/ --tag "$IMAGE" --project=gks-datalake-poc2-dev
echo "$IMAGE"
```

**Check:** the build ends with `SUCCESS`, and
`gcloud artifacts docker images list us-central1-docker.pkg.dev/gks-datalake-poc2-dev/poc --include-tags` lists the tag.

If the build is refused with a permission error on the bucket or the repository, the Cloud Build service account
needs `roles/artifactregistry.writer` on repo `poc`. Ask before granting it.

## Step 4: Terraform: plan, read, apply

Add the image to `terraform/shared/terraform.tfvars` (the full value printed by `echo "$IMAGE"`):

```hcl
simulator_image = "us-central1-docker.pkg.dev/gks-datalake-poc2-dev/poc/poc-source-simulator:<tag>"
```

```bash
cd terraform/shared
terraform init -backend-config=backend.hcl     # only if .terraform is missing
terraform plan -out=a8.tfplan
```

**Read the plan before applying.** Expect:

- `6 to add`: `google_service_account.simulator`, `google_project_iam_member.simulator_sql_client`,
  `google_secret_manager_secret_iam_member.simulator_password`, `google_cloud_run_v2_job.simulator`,
  `google_cloud_run_v2_job_iam_member.orchestrator_runs_simulator`, `google_cloud_scheduler_job.simulator_tick`.
- `2 to change`: the `poc-night-off` and `poc-morning-on` scheduler jobs (`http_target.body`: the workflow argument
  now names `poc-simulator-tick`). Their `paused` state isn't touched.
- `0 to destroy`, and nothing on `poc-ops-db`, `poc-cdc-stream` or any secret.

Anything else: stop and ask. Then:

```bash
terraform apply a8.tfplan
cd ../..
```

Commit the `terraform.tfvars` change (`A8: simulator image <tag>`).

**Check:**

```bash
gcloud run jobs describe poc-source-simulator --region=us-central1 --format="value(template.template.serviceAccount)"
gcloud scheduler jobs describe poc-simulator-tick --location=us-central1 --format="value(state,schedule)"  # PAUSED */5 * * * *
```

## Step 5: One tick by hand, then V1–V3

```bash
gcloud run jobs execute poc-source-simulator --region=us-central1 --wait
```

Then run **V1, V2, V3** below. Don't switch the schedule on until all three pass.

## Step 6: Switch the schedule on

```bash
gcloud scheduler jobs resume poc-simulator-tick --location=us-central1
```

Note the time. The first run starts at the next 5-minute mark.

## Step 7: Watch it for 2 hours, then V4–V7

Look in now and then with V5. After 2 hours run **V4** (AT-15 against staging), **V5**, **V6** and **V7**.

## Step 8: Rate, pause switch, failure test (V8–V10)

Once each, in any order; each takes a few minutes.

## Step 9: Evening

Pause the simulator **before** the database stops:

```bash
gcloud scheduler jobs pause poc-simulator-tick --location=us-central1
```

then the usual order: pause the stream, then stop the database. In the morning: start the database, resume the
stream, then `gcloud scheduler jobs resume poc-simulator-tick --location=us-central1`.

## Later: case events (closes A8)

1. A6 applied: a test message lands in `raw_lpos.case_event` (`A6_STEPS.md` step 5).
2. In A6's `pubsub_bq` call add `google_pubsub_topic_iam_member "simulator_publisher"`, role
   `roles/pubsub.publisher`, member `serviceAccount:sa-simulator@gks-datalake-poc2-dev.iam.gserviceaccount.com`.
3. A7's publisher merged as `simulator/case_events.py` with
   `publish_case_events(topic, n, rng) -> int` (the tick calls it); add `google-cloud-pubsub` to
   `requirements-runtime.txt`. Rebuild (step 3), update `simulator_image`.
4. Set `simulator_case_topic = "projects/gks-datalake-poc2-dev/topics/poc-case-events"`, plan, apply.
5. One tick by hand, V7's case-event rows, then another 2-hour watch (V5–V7).

Until then, A8's G2 and heartbeat part is complete but A8 itself is not "done".

## Record it

Tell me the results of V1–V10 (or paste them). They go in the guide's 17.0 row for A8, in
`COMPLETE_POC_A_STATUS.md` and `G2_CHANGE_PATH_STATUS.md`, and as evidence in
`docs/poc2/evidence/a8_<UTC time>.txt`.

---

## Verify: is it working?

### V1. The execution succeeded

```bash
gcloud run jobs executions list --job=poc-source-simulator --region=us-central1 --limit=1 \
  --format="table(name, status.completionTime, status.succeededCount, status.failedCount)"
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="poc-source-simulator"' \
  --limit=10 --freshness=15m --format="value(textPayload)"
```

**Pass:** `succeededCount = 1`, and the log has a line like
`tick rate=1.0 opened=5 updated=6 closed=2 deleted=0 moved=0 planted=0 history=13 case_events=off wheel_events=off crm=no heartbeat=ok`.

| Log says | Cause |
| --- | --- |
| `connection ... /cloudsql/... failed` / `No such file or directory` | Socket volume or `roles/cloudsql.client` missing; or the database is stopped |
| `password authentication failed for user "simulator_user"` | Wrong secret, or the password in the secret differs from the database user's |
| `Permission denied on secret` (execution doesn't start) | The secret grant to `sa-simulator` |
| `permission denied for table ...` | `simulator_user` is missing a grant from A2 (`sql/g2/replication.sql`) |

### V2. Cloud SQL changed (the source)

```bash
cloud-sql-proxy gks-datalake-poc2-dev:us-central1:poc-ops-db --port 5433 &
PGPASSWORD=$(gcloud secrets versions access latest --secret=poc-ops-db-simulator) \
  psql "host=localhost port=5433 dbname=g2 user=simulator_user"
```

```sql
SELECT source, beat_at, now() - beat_at AS age FROM g2.heartbeat ORDER BY source;
SELECT count(*) AS incidents, count(*) FILTER (WHERE resolved_at IS NULL) AS open FROM g2.alert_incidents;
SELECT max(incident_id) AS newest FROM g2.alert_incidents;
SELECT count(*) AS probe_incidents FROM g2.alert_incidents WHERE device_id = 'D999' OR store_id = 'S999';
```

**Pass:** the `simulator` row is under 5 minutes old; `newest` matches the last id in the log's `opened` list;
`probe_incidents` is the same before and after a tick.

### V3. The change reached BigQuery through CDC (the G2 change path)

Wait 2–5 minutes after the tick (Datastream latency, `cdc.md`).

```sql
SELECT MAX(TIMESTAMP_MILLIS(datastream_metadata.source_timestamp)) AS newest_change
FROM `gks-datalake-poc2-dev.raw_g2.g2_alert_incidents`;

SELECT MAX(beat_at) AS newest_beat
FROM `gks-datalake-poc2-dev.raw_g2.g2_heartbeat` WHERE source = 'simulator';

SELECT datastream_metadata.change_type AS change_type, COUNT(*) AS changes
FROM `gks-datalake-poc2-dev.raw_g2.g2_alert_incidents`
WHERE TIMESTAMP_MILLIS(datastream_metadata.source_timestamp) > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 MINUTE)
GROUP BY change_type;
```

**Pass:** `newest_change` and `newest_beat` within ~5 minutes of the tick; `INSERT` rows equal the opened count,
`UPDATE` rows equal updated + closed. `DELETE` shows up in about 1 tick in 10.

### V4. Current state still matches the source (AT-15 on staging)

The A10 views are on `main` now (all 11). Build them into your own dataset exactly as in `CRITICAL_PATH_G6.md`
stage 4, then run AT-15 against that dataset. AT-15 pauses `poc-simulator-tick` itself, waits for a fresh heartbeat
in `raw_g2`, compares 11 counts and resumes the scheduler.

```bash
export PYTHONUTF8=1
.venv/Scripts/dbt build --target local --select path:models/staging/g2       # PASS=38, as in CRITICAL_PATH_G6.md 4.1
.venv/Scripts/python.exe scripts/acceptance/at15_cdc_initial.py --stg-dataset dbt_<you>_stg
```

**Pass:** 11/11 after ticks have run. This proves the simulator's inserts, updates and deletes come out right in
current state, not only the first copy.

### V5. Every tick, for 2 hours

```bash
gcloud run jobs executions list --job=poc-source-simulator --region=us-central1 --limit=30 \
  --format="table(name, status.startTime, status.completionTime, status.succeededCount, status.failedCount)"
```

**Pass:** about 24 executions, every one `succeededCount = 1`, 5 minutes apart, each finishing in well under 240 s.
One failure: fix it and start the 2 hours again.

### V6. The heartbeat never went stale

```sql
SELECT beat_at,
       TIMESTAMP_DIFF(beat_at, LAG(beat_at) OVER (ORDER BY beat_at), SECOND) AS gap_s
FROM `gks-datalake-poc2-dev.raw_g2.g2_heartbeat`
WHERE source = 'simulator' AND beat_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR)
ORDER BY beat_at;
```

**Pass:** about 24 rows, gaps about 300 s, none over 480 s (the watchdog's 8-minute limit).

### V7. Every source changes

| Source | Check | Pass |
| --- | --- | --- |
| G2 incidents/history | V3 query with `INTERVAL 2 HOUR` | INSERT, UPDATE and at least one DELETE |
| Heartbeat | V6 | ~24 beats |
| Case events (after "Later") | `SELECT COUNT(*) FROM raw_lpos.case_event WHERE publish_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 10 MINUTE)` | ≥ 2 every 10 minutes, never 0 |
| Case duplicates (after "Later") | runbook phase 7 "planted duplicates" query | a few `event_id`s with 2 copies |
| CRM (when B2's bucket exists) | `gcloud storage ls gs://<bucket>/crm/` | one new export per hour |

### V8. Rate setting

Quick check without Terraform (an override for one execution):

```bash
gcloud run jobs execute poc-source-simulator --region=us-central1 --wait --update-env-vars=RATE=0.5
```

**Pass:** the log line shows `rate=0.5` and about half the opened/updated/closed counts (each 1–3). The permanent
setting is `simulator_rate` in `terraform.tfvars` (plan shows only the job's `RATE` changing).

### V9. Pause switch

```bash
gcloud scheduler jobs pause poc-simulator-tick --location=us-central1
# wait 10 minutes, then:
gcloud run jobs executions list --job=poc-source-simulator --region=us-central1 --limit=3
gcloud scheduler jobs resume poc-simulator-tick --location=us-central1
```

**Pass:** no new execution while paused; the next one at the 5-minute mark after resuming.

### V10. A failed tick doesn't beat

Before A7 exists, setting `CASE_TOPIC` makes the tick fail after its G2 changes:

```bash
gcloud run jobs execute poc-source-simulator --region=us-central1 --wait \
  --update-env-vars=CASE_TOPIC=projects/gks-datalake-poc2-dev/topics/does-not-exist
```

**Pass:** the execution fails with `CASE_TOPIC is set, but this image has no case-event publisher yet (task A7)`,
and `g2.heartbeat` for `simulator` keeps its old `beat_at` (V2's first query). The tick's G2 changes still commit;
that is expected. This proves the heartbeat is the last step.

## Pitfalls

- **Night routine:** pause `poc-simulator-tick` before `poc-ops-db` stops (step 9).
- **Don't set `simulator_case_topic`** until the A7 publisher is in the image: every tick would fail.
- Never run `seed` or `seed --reset` against Cloud SQL; the image's command is `tick`, and it has no generator.
- Never change S999/D999 by hand: AT-16 and AT-22 use them as probes. The tick leaves them alone.
- `terraform apply` won't change `paused` on the scheduler: use `gcloud scheduler jobs pause|resume`.
- A tick over 5 minutes would overlap the next. Ticks take seconds; the 240 s timeout guards it.
