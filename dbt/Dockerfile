# poc-dbt-runner-<env> (E3). Build context: the REPOSITORY ROOT, because the image holds dbt/ and orchestration/publish/
# (cloudbuild/main.yaml builds it on every merge to main, tagged with the commit SHA).
#   docker build -f dbt/Dockerfile -t dbt-runner --build-arg GIT_SHA=$(git rev-parse HEAD) .
#
# Layout in the image:  /app/dbt  (the dbt project, the working directory)  and  /app/orchestration/publish
# The job sets DBT_TARGET (dev or int) and GCP_PROJECT; it authenticates as sa-dwh-writer-<env> (application default credentials).
FROM python:3.12-slim

ARG GIT_SHA=unknown
LABEL org.opencontainers.image.revision=$GIT_SHA \
      org.opencontainers.image.title="poc-dbt-runner"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DBT_PROFILES_DIR=/app/dbt \
    DBT_SEND_ANONYMOUS_USAGE_STATS=false \
    GIT_SHA=$GIT_SHA

WORKDIR /app

# Python packages first, so this layer is reused when only models change
COPY dbt/requirements.txt /tmp/dbt-requirements.txt
COPY orchestration/publish/requirements.txt /tmp/publish-requirements.txt
RUN pip install -r /tmp/dbt-requirements.txt -r /tmp/publish-requirements.txt

COPY dbt /app/dbt
COPY orchestration/publish /app/orchestration/publish

# dbt packages (dbt_utils, dbt_expectations) are installed now, from package-lock.yml, so a run never needs hub.getdbt.com
RUN cd /app/dbt && dbt deps

# CRLF from a Windows checkout would break the script
RUN sed -i 's/\r$//' /app/dbt/entrypoint.sh \
 && useradd --uid 10001 --no-create-home runner \
 && chown -R runner /app/dbt

USER runner
WORKDIR /app/dbt
ENTRYPOINT ["bash", "/app/dbt/entrypoint.sh"]
CMD ["microbatch"]
