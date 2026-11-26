# poc-crm-loader (B3, B5). Build context: loaders/crm (cloudbuild/main.yaml builds it on every merge to main,
# tagged with the commit SHA).
#   docker build -t crm-loader loaders/crm
#
# The loader takes everything from its command line, so the Cloud Run job must pass the arguments:
#   --bucket <crm exports bucket> --prefix crm --project <project>      (add --approve export_ts=<ts> to release a HELD export)
FROM python:3.12-slim

ARG GIT_SHA=unknown
LABEL org.opencontainers.image.revision=$GIT_SHA \
      org.opencontainers.image.title="poc-crm-loader"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY crm_loader.py create_raw_crm.py ./

RUN useradd --uid 10001 --no-create-home loader
USER loader

ENTRYPOINT ["python", "/app/crm_loader.py"]
