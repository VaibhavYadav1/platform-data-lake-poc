# poc-source-simulator (task A8). Build context: this folder.
#   gcloud builds submit simulator/ --tag us-central1-docker.pkg.dev/gks-datalake-poc2-dev/poc/poc-source-simulator:<tag>
# The code goes into /app/simulator so `python -m simulator` finds the package (the guide's `COPY . .` didn't).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements-runtime.txt .
RUN pip install -r requirements-runtime.txt

COPY . /app/simulator/

RUN useradd --uid 10001 --no-create-home sim
USER sim

ENTRYPOINT ["python", "-m", "simulator"]
CMD ["tick"]
